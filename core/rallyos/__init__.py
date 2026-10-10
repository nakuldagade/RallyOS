"""RallyOS core SDK: training-free racket-sports intelligence from one camera."""

from rallyos.device import get_device
from rallyos.sports import list_sports, load_sport

__version__ = "0.1.0"
__all__ = ["get_device", "list_sports", "load_sport", "__version__"]
