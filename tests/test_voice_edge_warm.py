"""Sıcak bağlantı yolu: ağ olmadan sınanabilen tek şey sözleşmesi."""
import unittest

from modules import voice_edge_warm as warm


class WarmTests(unittest.TestCase):
    def test_ssml_escapes_text_and_carries_the_exact_voice(self):
        # Seslendirme metni değiştirmez: '<' ve '&' kaçışlanır, kimlik aynı kalır.
        xml = warm.ssml("A & B <C>", "tr-TR-AhmetNeural", "+8%", "+0Hz")
        self.assertIn("<voice name='tr-TR-AhmetNeural'>", xml)
        self.assertIn("A &amp; B &lt;C&gt;", xml)
        self.assertIn("rate='+8%'", xml)

    def test_without_a_warm_socket_the_audio_path_never_connects(self):
        # Sıcak bağlantı yoksa ses yolu bugünkü yola düşer; burada bağlanmaya
        # kalkışsa test ağ bekleyip zaman aşımına uğrardı.
        self.assertEqual(warm.synthesize("Merhaba", "tr-TR-AhmetNeural", "+0%", "+0Hz"), None)


if __name__ == "__main__":
    unittest.main()


class WarmBinaryTests(unittest.TestCase):
    def test_audio_header_is_stripped_from_the_binary_message(self):
        # Kullanıcının duyduğu "bozuk ses" buydu: başlık MP3 sanılıp çözücüye
        # veriliyordu. Başlık ayrılır, ses verisi aynen kalır.
        from modules import voice_edge_warm as warm
        header = b"X-RequestId:abc\r\nPath:audio\r\nContent-Type:audio/mpeg"
        payload = header + b"\r\n" + b"ID3-audio"
        # Edge'in biçimi: ilk iki bayt başlık bloğunun (uzunluk alanı dahil)
        # boyu; ses verisi ondan iki bayt sonra başlar.
        message = (len(header) + 2).to_bytes(2, "big") + payload
        headers, data = warm.split_binary(message)
        self.assertEqual(headers[b"Path"], b"audio")
        self.assertEqual(headers[b"Content-Type"], b"audio/mpeg")
        self.assertEqual(data, b"ID3-audio")

    def test_a_short_or_inconsistent_message_is_rejected(self):
        from modules import voice_edge_warm as warm
        with self.assertRaises(ValueError):
            warm.split_binary(b"\x01")
        with self.assertRaises(ValueError):
            warm.split_binary((400).to_bytes(2, "big") + b"kisa")


if __name__ == "__main__":
    unittest.main()
