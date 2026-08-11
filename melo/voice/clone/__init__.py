"""Voice cloning providers.

Melo ships a stub provider so the rest of the app has a concrete
CloneProvider to register. Additional implementations (e.g.
`rvc_clone.py` for RVC) live under this package behind the same
interface.
"""

from melo.voice.clone.stub_clone import StubCloneProvider

__all__ = ["StubCloneProvider"]
