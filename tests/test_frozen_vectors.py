"""Frozen reference-byte comparisons and independent APK-related fixtures."""
import gzip
import json
from pathlib import Path
import unittest

from awox import lighting
from vector_adapter import ExtendedCommandBuilder


class FrozenReferenceVectors(unittest.TestCase):
    def test_all_frozen_reference_vectors(self):
        path = Path(__file__).parent / 'fixtures/protocol_reference_vectors.json.gz'
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            vectors = json.load(f)
        self.assertEqual(len(vectors), 22546)
        key = bytes(range(16))
        for family, name, args, kwargs, expected in vectors:
            if family == 'builder':
                actual = getattr(ExtendedCommandBuilder(args[0]), name)(*args[1:], **kwargs).plaintext
            else:
                actual = getattr(lighting, name)(key, 0x1234, *args, **kwargs)
            self.assertEqual(actual.hex(), expected, (family, name, args, kwargs))


if __name__ == '__main__':
    unittest.main()
