"""VideoTool: A transcript-first tool for extracting topic-focused videos from streams."""

import logging
import sys

__version__ = "0.1.6"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("videotool")
