"""Receive an exact HTTP body without loading the complete upload in memory."""
from pathlib import Path

CHUNK_SIZE = 1 << 20

def receive(source, destination, size):
    left = size
    with Path(destination).open('wb') as output:
        while left:
            chunk = source.read(min(left, CHUNK_SIZE))
            if not chunk:
                raise ValueError('Dosya yüklemesi yarıda kaldı; yeniden yükle.')
            output.write(chunk)
            left -= len(chunk)
