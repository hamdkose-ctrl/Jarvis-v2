"""Telefon sunucusu erken red yanıtlarında (429/400/401/403) küçük POST gövdesini okuyup bağlantıyı düzgün kapatır.

Regresyon (14 Ekim 2026): `test_pair_endpoint_limits_bad_json_size_and_attempts` Windows'ta 429 yanıtında bağlantı
kesilmesiyle düşüyordu. Sunucu gövdeyi okumadan yanıt verip soketi kapatınca alıcı tamponda okunmamış veri kalır;
Windows (ve Linux) bu durumda FIN yerine RST gönderir ve istemci yanıtı okuyamadan `ConnectionResetError`/
`ConnectionAbortedError` alır. Güvenlik sınırları (deneme sayısı, 1024 bayt sınırı) değişmez; yalnız en fazla 64 KiB'lık
küçük gövde en çok 1 sn beklenerek tüketilir ve yanıt `Connection: close` ile gider.
"""
import socket
import time
import unittest

import test_phone_user_tokens as base


class PhoneRejectDrainTests(unittest.TestCase):
    setUp, tearDown = base.PhoneUserTokenTests.setUp, base.PhoneUserTokenTests.tearDown

    def raw(self, port, body, path='/api/pair'):
        s = socket.create_connection(('127.0.0.1', port), timeout=5)
        try:
            head = (b'POST ' + path.encode() + b' HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n'
                    b'Content-Length: %d\r\n\r\n' % len(body))
            half = len(body) // 2
            s.sendall(head + body[:half])
            time.sleep(0.15)                      # gövdenin geri kalanı yavaş ağdaki gibi sonra gelir
            s.sendall(body[half:])                # gövdeyi okumadan kapanmış sunucu buna RST ile karşılık verir
            time.sleep(0.2)
            out = b''
            while True:
                chunk = s.recv(65536)             # RST'de ConnectionResetError: test düşer
                if not chunk:
                    break
                out += chunk
            return out
        finally:
            s.close()

    def test_rejections_deliver_response_and_close_cleanly(self):
        srv = self.phone.PhoneServer(base._FakeEngine(), port=0)
        srv.start()
        try:
            port = srv._httpd.server_address[1]
            for body in (b'x' * 1025, b'x' * 60000, b'not-json'):   # 60 KB: sunucunun 8 KB okuma tamponunu aşar
                out = self.raw(port, body)
                self.assertTrue(out.startswith(b'HTTP/1.0 400') or out.startswith(b'HTTP/1.1 400'), out[:80])
            for _ in range(8):
                self.assertIn(b' 401 ', self.raw(port, b'{"code":"wrong"}').split(b'\r\n')[0] + b' ')
            for body in (b'{"code":"wrong"}', b'{"code":"wrong"}' * 3500):     # deneme sınırı aşıldı: gövde okunmadan
                out = self.raw(port, body)
                self.assertIn(b' 429 ', out.split(b'\r\n')[0] + b' ')
                self.assertIn(b'connection: close', out.lower())
            out = self.raw(port, b'{"x":1}', path='/api/notes')              # yetkisiz uç: deneme sınırı aşıldı
            self.assertIn(b' 429 ', out.split(b'\r\n')[0] + b' ')
        finally:
            srv.stop()

    def test_large_body_is_not_read(self):
        srv = self.phone.PhoneServer(base._FakeEngine(), port=0)
        srv.start()
        try:
            port = srv._httpd.server_address[1]
            s = socket.create_connection(('127.0.0.1', port), timeout=5)
            try:
                # 2 MB söyleyip hiç göndermeyen istemci sunucuyu bekletmez: yanıt 1 sn içinde gelir
                s.sendall(b'POST /api/pair HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 2000000\r\n\r\n')
                start = time.monotonic()
                first = s.recv(4096)
                self.assertLess(time.monotonic() - start, 1.5)
                self.assertIn(b' 400 ', first.split(b'\r\n')[0] + b' ')
            finally:
                s.close()
        finally:
            srv.stop()


if __name__ == '__main__':
    unittest.main()
