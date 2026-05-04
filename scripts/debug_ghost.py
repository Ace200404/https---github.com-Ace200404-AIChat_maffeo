"""Debug: shows total article count, date range, and visibility breakdown from Ghost API."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pipeline.ghost_api import get_credentials, get_session, _make_jwt

ghost_url, admin_key = get_credentials()
token   = _make_jwt(admin_key)
session = get_session()

# Fetch ALL posts (all statuses, all visibility levels)
response = session.get(
    f"{ghost_url}/ghost/api/admin/posts/",
    headers={"Authorization": f"Ghost {token}"},
    params={
        "limit":  "all",
        "order":  "published_at desc",
        "fields": "id,title,status,visibility,published_at",
    },
    timeout=60,
)
response.raise_for_status()
posts = response.json().get("posts", [])

print(f"\nTotal posts returned by API: {len(posts)}")

# Group by status + visibility
from collections import Counter
status_counts     = Counter(p.get("status") for p in posts)
visibility_counts = Counter(p.get("visibility") for p in posts)

print("\nBy status:")
for k, v in status_counts.most_common():
    print(f"  {k}: {v}")

print("\nBy visibility:")
for k, v in visibility_counts.most_common():
    print(f"  {k}: {v}")

# Show newest 5 and oldest 5
published = [p for p in posts if p.get("status") == "published"]
print(f"\nPublished posts: {len(published)}")

if published:
    print("\nNewest 5:")
    for p in published[:5]:
        print(f"  {p.get('published_at', '')[:10]}  {p.get('visibility','?'):10}  {p.get('title','')[:60]}")
    print("\nOldest 5:")
    for p in published[-5:]:
        print(f"  {p.get('published_at', '')[:10]}  {p.get('visibility','?'):10}  {p.get('title','')[:60]}")
