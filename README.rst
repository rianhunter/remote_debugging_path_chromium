remote_debugging_path_chromium
==============================

`remote_debugging_path_chromium` is a wrapper script for chromium
that allows you to connect to the chromium debugger over a UNIX
domain socket. This is useful if you don't want to expose your
debugger socket over localhost (which might be a security concern).
For additional security it also provides whitelist functionality to
only allow certain debugger methods.

Installation
------------

Easiest way is to install from PyPI via `pip3`:

    $ pip3 install remote_debugging_path_chromium

Usage
-----

Use it the same way you would use chromium except it provides two
extra options:

    - --remote-debugging-path=PATH
      This specifies the path on which you want the chromium remote
      debugger to listen.

    - --remote-debugging-allow=METHOD
      This turns on whitelist functionality, limiting which methods
      are allowed to be invoked through this interface. You can specify
      this multiple times.

Assuming your pip install location is on your PATH, you can invoke
it like you would invoke chromium.
      
    $ remote_debugging_path_chromium

Contact
-------

Rian Hunter `@cejetvole <https://twitter.com/cejetvole>`_



