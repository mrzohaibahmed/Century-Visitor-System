"""A tiny SMTP server for tests (no real mail server needed): records messages, or answers like a
server that refuses a recipient (550) or asks to try later (451). No STARTTLS, no AUTH."""
import email
import socketserver
import threading
from email.message import Message


class FakeSMTP:
    def __init__(self, mode: str = "ok", port: int = 0):
        self.mode = mode                                  # ok | reject (550) | tempfail (451)
        self.messages: list[Message] = []
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, line: str) -> None:
                self.wfile.write((line + "\r\n").encode())

            def handle(self) -> None:
                self.reply("220 fake.smtp ready")
                while line := self.rfile.readline():
                    command = line.decode(errors="replace").strip().upper()
                    if command.startswith(("EHLO", "HELO")):
                        self.reply("250-fake.smtp")
                        self.reply("250 8BITMIME")
                    elif command.startswith("RCPT"):
                        self.reply({"reject": "550 5.1.1 no such user", "tempfail": "451 4.3.0 try later"}
                                   .get(owner.mode, "250 OK"))
                    elif command == "DATA":
                        self.reply("354 go ahead")
                        data = b""
                        while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                            data += chunk
                        owner.messages.append(email.message_from_bytes(data))
                        self.reply("250 queued")
                    elif command == "QUIT":
                        self.reply("221 bye")
                        return
                    else:                                  # MAIL, RSET, NOOP
                        self.reply("250 OK")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeSMTP":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
