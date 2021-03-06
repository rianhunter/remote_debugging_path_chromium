#!/usr/bin/env python3

# remote_debugging_path_chromium is free software: you can
# redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.

# remote_debugging_path_chromium is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with remote_debugging_path_chromium.  If not, see
# <http://www.gnu.org/licenses/>.

from aiohttp import web

import asyncio
import json
import re
import socket
import sys
import os
import uuid

class ChromeError(Exception):
    def __init__(self, error_object):
        super().__init__(error_object['code'], error_object['message'])
        self.code = error_object['code']
        self.message = error_object['message']

    def __str__(self):
        return '[Code %s] %s' % (self.code, self.message)

@asyncio.coroutine
def start_with_unix_path(whitelist, unix_path, argv, csock):
    (reader, writer) = yield from asyncio.open_connection(sock=csock)

    messages = {}
    curid = 0
    sessions = {}

    @asyncio.coroutine
    def send_message(msg):
        nonlocal curid

        fut = asyncio.Future()

        msg['id'] = curid
        messages[curid] = fut

        writer.write(json.dumps(msg).encode('utf-8'))
        writer.write(b'\0')

        curid += 1

        yield from writer.drain()

        return (yield from fut)

    @asyncio.coroutine
    def call_method(name, **kw):
        res = yield from send_message(dict(
            method=name,
            params=kw,
        ))
        return res

    @asyncio.coroutine
    def get_rdp_message(reader):
        msg = b''
        while True:
            b = yield from reader.read(1)
            if not b:
                return None
            if not b[0]:
                break
            msg += b
        return json.loads(msg.decode('utf-8'))

    @asyncio.coroutine
    def manage_pipe():
        while True:
            msg = yield from get_rdp_message(reader)
            if msg is None:
                for sessionq in sessions.values():
                    yield from sessionq.put(None)
                break

            # event message meant for specific session
            if msg.get("sessionId") is not None:
                yield from sessions[msg.get("sessionId")].put(msg)
                continue

            mid = msg.get("id")
            if mid is not None and mid in messages:
                fut = messages.pop(mid)
                if "error" in msg:
                    fut.set_exception(ChromeError(msg.get("error")))
                else:
                    fut.set_result(msg.get("result"))
            else:
                if msg.get('method') == 'Target.receivedMessageFromTarget':
                    sessionId = msg['params']["sessionId"]
                    if sessionId in sessions:
                        yield from sessions[sessionId].put(json.loads(msg['params']["message"]))
                elif msg.get('method') == 'Target.detachedFromTarget':
                    sessionId = msg['params']["sessionId"]
                    if sessionId in sessions:
                        yield from sessions[sessionId].put(None)

            # TODO: handle events
    asyncio.create_task(manage_pipe())

    app = web.Application()

    def target_to_json(target):
        return dict(
            description="",
            id=target['targetId'],
            title=target['title'],
            type=target['type'],
            url=target['url'],
            webSocketDebuggerUrl="ws:/devtools/page/%s" % (target['targetId'],),
        )

    browser_uuid = uuid.uuid4()
    browser_debugger_path = '/devtools/browser/%s' % (browser_uuid,)

    @asyncio.coroutine
    def json_version(request):
        res = yield from call_method('Browser.getVersion')

        mo = re.search(r'AppleWebKit/(\d+)\.(\d+)', res['userAgent'])
        if mo is not None:
            webkit_version = '%s.%s (%s)' % (mo[1], mo[2], res['revision'],)
        else:
            webkit_version = '0.0 (%s)' % (res['revision'],)

        return web.json_response({
            'Browser': res['product'],
            'Protocol-Version': res['protocolVersion'],
            'User-Agent': res['userAgent'],
            'V8-Version': res['jsVersion'],
            'WebKit-Version': webkit_version,
            'webSocketDebuggerUrl': 'ws:%s' % (browser_debugger_path,),
        })

    @asyncio.coroutine
    def json_new(request):
        target = yield from send_message(dict(
            method="Target.createTarget",
            params=dict(
                url="",
            ),
        ))

        targetId = target['targetId']

        targets = yield from send_message(dict(
            method="Target.getTargets",
            params=dict(
                targetId=targetId,
            ),
        ))

        for target in targets['targetInfos']:
            if target['targetId'] == targetId:
                return web.json_response(target_to_json(target))

        raise Exception("target went missing!")

    @asyncio.coroutine
    def json_list(request):
        targets = yield from send_message({"method": "Target.getTargets"})

        ret = []
        for target in targets['targetInfos']:
            ret.append(target_to_json(target))
        return web.json_response(ret)

    @asyncio.coroutine
    def json_close(request):
        res = yield from send_message(dict(
            method="Target.closeTarget",
            params=dict(
                targetId=request.match_info['id'],
            ),
        ))

        # Target is closing
        if res['success']:
            return web.Response(text="Target is closing")
        else:
            # TODO 404: "No such target id: {targetId}"
            return web.Response(text="Failed to close...")

    @asyncio.coroutine
    def devtools_socket(request):
        if request.path == browser_debugger_path:
            res = yield from call_method('Target.attachToBrowserTarget')
            flat_mode = True
        else:
            targetId = request.match_info['id']
            res = yield from call_method('Target.attachToTarget', targetId=targetId)
            flat_mode = False
        sessionId = res['sessionId']

        session_queue = asyncio.Queue()

        sessions[sessionId] = session_queue

        ws = None
        try:
            ws = web.WebSocketResponse(autoclose=False)
            yield from ws.prepare(request)

            taskws = asyncio.create_task(ws.receive())
            taskq = asyncio.create_task(session_queue.get())

            while True:
                (done, pending) = yield from asyncio.wait([taskws, taskq], return_when=asyncio.FIRST_COMPLETED)

                if taskws in done:
                    msg = yield from taskws

                    if msg.type != web.WSMsgType.TEXT:
                        taskq.cancel()
                        # unhandled
                        break

                    wmsg = None
                    if whitelist is not None:
                        wmsg = json.loads(msg.data)

                        # evaluate each whitelist expression
                        # to check if it matches
                        for expr in whitelist:
                            if eval(expr, {}, dict(msg=wmsg)):
                                break
                        else:
                            yield from ws.send_json(dict(
                                id=wmsg['id'],
                                error=dict(
                                    code=-32000,
                                    message="not allowed",
                                ),
                            ))
                            taskws = asyncio.create_task(ws.receive())
                            continue

                    if flat_mode:
                        if wmsg is None:
                            wmsg = json.loads(msg.data)
                        wmsg['sessionId'] = sessionId

                        writer.write(json.dumps(wmsg).encode('utf-8'))
                        writer.write(b'\0')
                        yield from writer.drain()
                    else:
                        yield from call_method(
                            'Target.sendMessageToTarget',
                            message=msg.data,
                            sessionId=sessionId,
                        )

                    taskws = asyncio.create_task(ws.receive())

                if taskq in done:
                    tosend = yield from taskq
                    if tosend is None:
                        taskws.cancel()
                        break
                    tosend.pop("sessionId", None)
                    yield from ws.send_json(tosend)
                    taskq = asyncio.create_task(session_queue.get())
        finally:
            del sessions[sessionId]
            try:
                yield from call_method('Target.detachFromTarget', sessionId=sessionId)
            except ChromeError as e:
                if e.code != -32602:
                    raise
            if ws is not None:
                yield from ws.close()

    app.add_routes([
        web.get("/json/version", json_version),
        web.get("/json/new", json_new),
        web.get("/json/list", json_list),
        web.get("/json/close/{id}", json_close),
        web.get("/devtools/page/{id}", devtools_socket),
        web.get(browser_debugger_path, devtools_socket),
    ])

    dead_fut = asyncio.Future()

    runner = web.AppRunner(app)
    yield from runner.setup()
    site = web.UnixSite(runner, unix_path)
    yield from site.start()

    chrome_proc = yield from asyncio.create_subprocess_exec("chromium", *argv[1:],
                                                            pass_fds=(3, 4),
    )

    os.close(3)
    os.close(4)

    waited = False
    try:
        # TODO: wait for chrome to die
        yield from chrome_proc.wait()
        waited = True
    finally:
        yield from runner.cleanup()
        if not waited:
            chrome_proc.terminate()

def whitelist_method_to_expr(method_name):
    return 'msg.get("method") == %r' % (method_name,)

def main(argv=None):
    if argv is None:
        argv = sys.argv

    whitelist = None

    waiting_for_whitelist_expression = False
    waiting_for_whitelist = False
    waiting_for_path = False
    unix_path = None
    to_delete = []
    for (idx, value) in enumerate(argv):
        if not idx: continue

        if waiting_for_path:
            unix_path = value
            to_delete.append([idx - 1, idx + 1])
            waiting_for_path = False
            continue

        if waiting_for_whitelist:
            if whitelist is None:
                whitelist = []
            whitelist.append(whitelist_method_to_expr(value))
            waiting_for_whitelist = False
            continue

        if waiting_for_whitelist_expression:
            if whitelist is None:
                whitelist = []
            whitelist.append(value)
            waiting_for_whitelist_expression = False
            continue

        if value == "--remote-debugging-path":
            waiting_for_path = True
        elif value.startswith("--remote-debugging-path="):
            unix_path = value[len("--remote-debugging-path="):]
            to_delete.append([idx, idx + 1])

        if value == "--remote-debugging-allow":
            waiting_for_whitelist = True
        elif value.startswith("--remote-debugging-allow="):
            if whitelist is None:
                whitelist = []
            whitelist.append(whitelist_method_to_expr(value[len("--remote-debugging-allow="):]))
            to_delete.append([idx, idx + 1])

        if value == "--remote-debugging-allow-expression":
            waiting_for_whitelist_expression = True
        elif value.startswith("--remote-debugging-allow-expression="):
            if whitelist is None:
                whitelist = []
            whitelist.append(value[len("--remote-debugging-allow-expression="):])
            to_delete.append([idx, idx + 1])

    if unix_path is not None:
        argv = list(argv)
        for sl in to_delete:
            del argv[sl[0]:sl[1]]
        argv += ["--remote-debugging-pipe"]

        # reserve fds 3 and 4
        os.dup2(0, 3)
        os.dup2(0, 4)

        (csock, ssock) = socket.socketpair()

        os.dup2(ssock.fileno(), 3)
        os.dup2(ssock.fileno(), 4)
        ssock.close()

        asyncio.run(start_with_unix_path(whitelist, unix_path, argv, csock))
        return 0;

    if whitelist is not None:
        raise Exception("Whitelist has no effect without --remote-debugging-path!")

    return os.execvp("chromium", argv)

if __name__ == "__main__":
    sys.exit(main(sys.argv))
