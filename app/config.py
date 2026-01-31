import os
from dotenv import load_dotenv

load_dotenv()

PLATFORM_ADMIN_KEY = os.getenv("PLATFORM_ADMIN_KEY", "")
