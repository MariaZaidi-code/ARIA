"""Document share-link contract (api/document_routes.py).

Covers token minting/rotation, the public read-only endpoint, expiry
fail-closed behavior, unshare, and the shared-with-me listing.
"""

import auth
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import document_routes
from insight_rag import config as rag_config
from insight_rag.storage import RAGMetadataStore

SHARER = {"user_id": 902601, "username": "sharer@example.test",
          "email": "sharer@example.test"}
READER = {"user_id": 902602, "username": "reader@example.test",
          "email": "reader@example.test"}
DOC_ID = "doc-share-1"
DOC = {
    "document_id": DOC_ID,
    "filename": "share-me.pdf",
    "summary": "A shareable summary.",
}


class DocumentShareLinkTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="aria_share_"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))

        # Isolate the RAG users dir + auth DB for this test process.
        orig_users = rag_config.RAG_USERS_DIR
        users = tmp / "rag_users"
        users.mkdir(parents=True, exist_ok=True)
        rag_config.RAG_USERS_DIR = users
        self.addCleanup(setattr, rag_config, "RAG_USERS_DIR", orig_users)

        orig_db = auth.DB_PATH
        auth.DB_PATH = tmp / "auth.db"
        self.addCleanup(setattr, auth, "DB_PATH", orig_db)

        app = FastAPI()
        app.include_router(document_routes.router)
        app.dependency_overrides[document_routes.require_writable] = (
            lambda: SHARER
        )
        app.dependency_overrides[document_routes.get_current_user] = (
            lambda: READER
        )
        self.client = TestClient(app)

        self.meta = RAGMetadataStore(SHARER["user_id"])
        self.meta.put_document(dict(DOC))
        token = auth.issue_token(SHARER["user_id"], SHARER["username"],
                                 ttl_hours=1)
        self.headers = {"Authorization": f"Bearer {token}"}

    def test_share_fetch_unshare_cycle(self):
        r = self.client.post(f"/api/documents/{DOC_ID}/share",
                             headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text[:300])
        token = r.json()["share_token"]
        self.assertGreaterEqual(len(token), 20)
        self.assertIn(f"/api/documents/shared/{token}", r.json()["share_url"])

        pub = self.client.get(f"/api/documents/shared/{token}")
        self.assertEqual(pub.status_code, 200, pub.text[:300])
        self.assertTrue(pub.json()["ok"])
        self.assertEqual(pub.json()["document"]["filename"], DOC["filename"])
        # Secrets never appear in the public payload.
        for banned in ("share_token", "shared_with", "shared",
                       "share_expires_at"):
            self.assertNotIn(banned, pub.json()["document"])

        # Unshare revokes immediately.
        r2 = self.client.delete(f"/api/documents/{DOC_ID}/share",
                                headers=self.headers)
        self.assertEqual(r2.status_code, 200, r2.text[:300])
        gone = self.client.get(f"/api/documents/shared/{token}")
        self.assertEqual(gone.status_code, 404)

    def test_expired_link_is_fail_closed(self):
        r = self.client.post(f"/api/documents/{DOC_ID}/share",
                             headers=self.headers)
        token = r.json()["share_token"]
        ok = self.client.get(f"/api/documents/shared/{token}")
        self.assertEqual(ok.status_code, 200, ok.text[:300])

        doc = self.meta.get_document(DOC_ID)
        doc["share_expires_at"] = "2000-01-01T00:00:00+00:00"
        self.meta.put_document(doc)
        stale = self.client.get(f"/api/documents/shared/{token}")
        self.assertEqual(stale.status_code, 404)
        self.assertIn("expired", stale.json()["detail"])

    def test_malformed_expiry_is_fail_closed(self):
        self.client.post(f"/api/documents/{DOC_ID}/share", headers=self.headers)
        doc = self.meta.get_document(DOC_ID)
        doc["share_expires_at"] = "not-a-timestamp"
        self.meta.put_document(doc)
        token = doc["share_token"]
        self.assertEqual(
            self.client.get(f"/api/documents/shared/{token}").status_code, 404)

    def test_shared_with_me_listing_hides_token(self):
        self.client.post(f"/api/documents/{DOC_ID}/share", headers=self.headers)
        doc = self.meta.get_document(DOC_ID)
        doc["shared_with"] = [READER["username"]]
        self.meta.put_document(doc)

        responded = self.client.get("/api/documents/shared-with-me")
        self.assertEqual(responded.status_code, 200, responded.text[:300])
        docs = responded.json()["documents"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["filename"], DOC["filename"])
        self.assertNotIn("share_token", docs[0])


if __name__ == "__main__":
    unittest.main()
