"""Voice style transfer providers.

Melo ships a stub provider. Additional implementations (e.g.
`rvc_style.py`) live under this package behind the same interface.
"""

from melo.voice.style.stub_style import StubStyleProvider

__all__ = ["StubStyleProvider"]
