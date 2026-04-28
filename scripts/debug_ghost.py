"""Quick debug: prints the raw Ghost API response for the first article."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pipeline.ghost_api import get_credentials, get_session, _make_jwt

ghost_url, admin_key = get_credentials()
token   = _make_jwt(admin_key)
session = get_session()

response = session.get(
    f"{ghost_url}/ghost/api/admin/posts/",
    headers={"Authorization": f"Ghost {token}"},
    params={
        "include": "tags,authors",
        "formats": "plaintext",
        "limit":   "1",
        "filter":  "status:published",
    },
    timeout=30,
)
response.raise_for_status()
post = response.json()["posts"][0]

print("Keys in post:", list(post.keys()))
print("\ntitle:    ", post.get("title"))
print("plaintext:", repr(post.get("plaintext", "")[:300]))
print("html:     ", repr(post.get("html", "")[:300]))
