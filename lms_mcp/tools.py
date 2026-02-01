from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from .auth import AuthManager
from .http_client import HttpClient
from .session import session_store


def register_tools(mcp: FastMCP, client: HttpClient) -> None:
    """Register all Library tools with FastMCP."""
    auth = AuthManager(client, session_store)

    async def _call(
        method: str,
        path: str,
        *,
        access_token: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Internal helper that:
        - injects cached access token when access_token is omitted
        - refreshes expired tokens before the call
        - on a 401, attempts one refresh + retry before bubbling the error
        """
        token_to_use, bundle = await auth.access_token_for_call(access_token)

        async def _do_request(active_token: Optional[str]) -> Dict[str, Any]:
            return await client.request(
                method,
                path,
                access_token=active_token,
                params=params,
                json_body=json_body,
                data=data,
                files=files,
            )

        try:
            return await _do_request(token_to_use)
        except RuntimeError as err:
            if "401" not in str(err):
                raise
            refreshed = await auth.refresh_after_unauthorized(bundle)
            if refreshed:
                return await _do_request(refreshed.access_token)
            raise

    # ---------------- Public ----------------
    @mcp.tool()
    async def health_check() -> Dict[str, Any]:
        """
        Purpose: Lightweight liveness probe to confirm the MCP server can reach the LMS API.
        Inputs: none.
        Outputs: dict containing health status and backend timestamp.
        Behavior: Performs unauthenticated GET /api/health; useful for connectivity checks before other tools.
        """
        return await _call("GET", "health")

    @mcp.tool()
    async def list_books(
        page: int = 1,
        limit: int = 12,
        genre: Optional[str] = None,
        available_only: Optional[bool] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Retrieve a paginated slice of the catalog for browsing.
        Inputs:
        - page (int): 1-based page number.
        - limit (int): page size.
        - genre (str|None): filter to a single genre when provided.
        - available_only (bool|None): when True, restrict to titles with available copies.
        - sort (str|None): backend-defined sort key (e.g., newest, popular).
        Outputs: dict with `data.items` list of books plus pagination meta.
        Behavior: Issues GET /api/books with query params; attaches session auth if present though endpoint is public.
        """
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if genre:
            params["genre"] = genre
        if available_only is True:
            params["available"] = "true"
        if sort:
            params["sort"] = sort
        return await _call("GET", "books", params=params)

    @mcp.tool()
    async def search_books(query: str, page: int = 1, limit: int = 12) -> Dict[str, Any]:
        """
        Purpose: Full-text search across books.
        Inputs:
        - query (str): search string.
        - page (int): 1-based page number.
        - limit (int): page size.
        Outputs: paginated search results with relevance as defined by API.
        Behavior: GET /api/books/search?q=...; public endpoint but will send auth header when cached.
        """
        params = {"q": query, "page": page, "limit": limit}
        return await _call("GET", "books/search", params=params)

    @mcp.tool()
    async def get_book(book_id: str) -> Dict[str, Any]:
        """
        Purpose: Retrieve detailed information for a single book.
        Inputs:
        - book_id (str): MongoDB/DB identifier of the book.
        Outputs: dict describing the book, availability, and metadata.
        Behavior: GET /api/books/{id}; public but will include auth if cached.
        """
        return await _call("GET", f"books/{book_id}")

    @mcp.tool()
    async def get_genres() -> Dict[str, Any]:
        """
        Purpose: List all available genres for filtering.
        Inputs: none.
        Outputs: array of genre strings (or objects as defined by API).
        Behavior: GET /api/books/genres; no auth required.
        """
        return await _call("GET", "books/genres")

    # ---------------- Auth ----------------
    @mcp.tool()
    async def auth_register(
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Create a new user account in the LMS.
        Inputs:
        - email (str): unique email for the user.
        - password (str): plain password; transmitted only to API, not stored by MCP.
        - first_name (str), last_name (str): required profile fields.
        - phone (str|None): optional contact number.
        Outputs: dict with created user profile and an access token; backend also sets refresh cookie.
        Behavior: POST /api/auth/register with JSON body; caches no tokens automatically.
        """
        json_body = {
            "email": email,
            "password": password,
            "firstName": first_name,
            "lastName": last_name,
            "phone": phone,
        }
        return await _call("POST", "auth/register", json_body=json_body)

    async def _login_impl(email: str, password: str) -> Dict[str, Any]:
        """
        Shared helper for login tools:
        - Performs POST /api/auth/login with supplied credentials.
        - Extracts access/refresh tokens and caches them for the current MCP session.
        - Returns metadata only (status, cache flags); never persists or echoes the password.
        """
        bundle = await auth.login(email, password)
        return {
            "status": "ok",
            "cached": True,
            "hasRefreshToken": bool(bundle.refresh_token),
            "expiresAt": bundle.expires_at.isoformat() if bundle.expires_at else None,
        }

    @mcp.tool(name="login")
    async def login(email: str, password: str) -> Dict[str, Any]:
        """
        Purpose: Authenticate once per MCP session using email/password.
        Inputs:
        - email (str)
        - password (str)
        Outputs: minimal dict indicating success, whether a refresh token is stored, and access token expiry timestamp.
        Behavior: Caches tokens server-side; subsequent tools auto-send/refresh the access token without re-prompting.
        """
        return await _login_impl(email, password)

    @mcp.tool()
    async def auth_login(email: str, password: str) -> Dict[str, Any]:
        """
        Purpose: Backward-compatible alias for `login`.
        Inputs/Outputs/Behavior: identical to `login`.
        """
        return await _login_impl(email, password)

    @mcp.tool()
    async def auth_me(access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Fetch the profile of the currently authenticated user.
        Inputs:
        - access_token (str|None): override token; when omitted uses cached session token.
        Outputs: dict with user profile fields and role.
        Behavior: GET /api/auth/me with Authorization header; auto-refreshes token if expired.
        """
        return await _call("GET", "auth/me", access_token=access_token)

    @mcp.tool()
    async def update_profile(
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Edit the authenticated user's profile fields.
        Inputs:
        - first_name (str|None), last_name (str|None), phone (str|None): fields to update; omitted fields are untouched.
        - access_token (str|None): optional override; otherwise uses cached session token.
        Outputs: updated profile dict from backend.
        Behavior: PUT /api/auth/profile with JSON body of provided fields; requires valid auth and will auto-refresh once on 401.
        """
        json_body: Dict[str, Any] = {}
        if first_name is not None:
            json_body["firstName"] = first_name
        if last_name is not None:
            json_body["lastName"] = last_name
        if phone is not None:
            json_body["phone"] = phone
        return await _call("PUT", "auth/profile", access_token=access_token, json_body=json_body)

    @mcp.tool()
    async def auth_logout() -> Dict[str, Any]:
        """
        Purpose: Locally clear all cached tokens for the current MCP session.
        Inputs: none.
        Outputs: { "cached": False } confirmation.
        Behavior: Does not call the LMS API; simply removes in-memory token bundle so next tool will require login.
        """
        session_store.clear_current()
        return {"cached": False}

    # ---------------- Books (admin) ----------------
    @mcp.tool()
    async def create_book(
        isbn: str,
        title: str,
        author: str,
        description: Optional[str] = None,
        genre: Optional[str] = None,
        total_copies: Optional[int] = None,
        cover_image_path: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Admin-only creation of a new book record.
        Inputs:
        - isbn (str), title (str), author (str): required bibliographic data.
        - description (str|None), genre (str|None), total_copies (int|None): optional metadata.
        - cover_image_path (str|None): local file path; sent as multipart when provided.
        - access_token (str|None): admin token override; otherwise uses cached session token.
        Outputs: dict representing the created book.
        Behavior: POST /api/books; sends multipart when file is included, otherwise JSON. Requires admin auth; auto-refreshes token if needed.
        """
        data: Dict[str, Any] = {
            "isbn": isbn,
            "title": title,
            "author": author,
            "description": description,
            "genre": genre,
            "totalCopies": total_copies,
        }
        data = {k: v for k, v in data.items() if v is not None}

        files = None
        if cover_image_path:
            files = {"coverImage": client.file_payload(cover_image_path)}

        return await _call(
            "POST",
            "books",
            access_token=access_token,
            data=data if files else None,
            json_body=None if files else data,
            files=files,
        )

    @mcp.tool()
    async def update_book(
        book_id: str,
        isbn: Optional[str] = None,
        title: Optional[str] = None,
        author: Optional[str] = None,
        description: Optional[str] = None,
        genre: Optional[str] = None,
        total_copies: Optional[int] = None,
        cover_image_path: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Admin update of existing book metadata.
        Inputs:
        - book_id (str): target book.
        - isbn/title/author/description/genre/total_copies: fields to overwrite when provided.
        - cover_image_path (str|None): optional replacement cover.
        - access_token (str|None): admin token override.
        Outputs: updated book dict from backend.
        Behavior: PUT /api/books/{id}; merges provided fields, supports multipart when cover supplied; requires admin auth with auto-refresh support.
        """
        data: Dict[str, Any] = {
            "isbn": isbn,
            "title": title,
            "author": author,
            "description": description,
            "genre": genre,
            "totalCopies": total_copies,
        }
        data = {k: v for k, v in data.items() if v is not None}

        files = None
        if cover_image_path:
            files = {"coverImage": client.file_payload(cover_image_path)}

        return await _call(
            "PUT",
            f"books/{book_id}",
            access_token=access_token,
            data=data if files else None,
            json_body=None if files else data,
            files=files,
        )

    @mcp.tool()
    async def delete_book(book_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Remove a book (admin only).
        Inputs:
        - book_id (str): identifier of the book to delete.
        - access_token (str|None): admin token override.
        Outputs: deletion confirmation from backend.
        Behavior: DELETE /api/books/{id}; requires admin auth, auto-refresh on 401.
        """
        return await _call("DELETE", f"books/{book_id}", access_token=access_token)

    # ---------------- Borrow (user/admin) ----------------
    @mcp.tool()
    async def borrow_book(book_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Create a borrow request for the authenticated user.
        Inputs:
        - book_id (str): ID of the book to borrow.
        - access_token (str|None): user token override; defaults to cached token.
        Outputs: borrow record including status and due date when approved.
        Behavior: POST /api/borrows with JSON {bookId}; requires user auth, auto-refreshes once on 401.
        """
        return await _call("POST", "borrows", access_token=access_token, json_body={"bookId": book_id})

    @mcp.tool()
    async def return_book(borrow_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Mark a borrow as returned.
        Inputs:
        - borrow_id (str): borrow record identifier.
        - access_token (str|None): user/admin token override.
        Outputs: updated borrow record with returned state.
        Behavior: PUT /api/borrows/{id}/return; requires valid auth, auto-refresh supported.
        """
        return await _call("PUT", f"borrows/{borrow_id}/return", access_token=access_token)

    @mcp.tool()
    async def renew_book(borrow_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Request a renewal for an active borrow.
        Inputs:
        - borrow_id (str): target borrow record.
        - access_token (str|None): token override.
        Outputs: updated borrow record including new due date.
        Behavior: PUT /api/borrows/{id}/renew; user must be authenticated, with auto-refresh on expiry.
        """
        return await _call("PUT", f"borrows/{borrow_id}/renew", access_token=access_token)

    @mcp.tool()
    async def get_my_borrows(
        page: int = 1,
        limit: int = 10,
        status: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: List the current user's borrow history in pages.
        Inputs:
        - page (int), limit (int): pagination controls.
        - status (str|None): filter by borrow status (e.g., pending, approved, returned).
        - access_token (str|None): token override.
        Outputs: paginated borrow list, including fines info per record.
        Behavior: GET /api/borrows/my-borrows; requires user auth with auto-refresh.
        """
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if status:
            params["status"] = status
        return await _call("GET", "borrows/my-borrows", access_token=access_token, params=params)

    @mcp.tool()
    async def get_current_borrows(access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Quickly fetch active (non-returned) borrows for the current user.
        Inputs:
        - access_token (str|None): token override.
        Outputs: list of current borrows plus any outstanding fines totals.
        Behavior: GET /api/borrows/current with Authorization header; auto-refresh supported.
        """
        return await _call("GET", "borrows/current", access_token=access_token)

    @mcp.tool()
    async def get_my_fines(access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Retrieve fines associated with the authenticated user.
        Inputs:
        - access_token (str|None): token override.
        Outputs: list of fines and aggregated totals.
        Behavior: GET /api/borrows/my-fines; requires auth and auto-refresh will run when necessary.
        """
        return await _call("GET", "borrows/my-fines", access_token=access_token)

    @mcp.tool()
    async def pay_fine(borrow_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Mark a fine as paid for a specific borrow.
        Inputs:
        - borrow_id (str): borrow record that incurred the fine.
        - access_token (str|None): token override.
        Outputs: confirmation payload from backend.
        Behavior: PUT /api/borrows/{id}/pay-fine; requires auth with auto-refresh retry on 401.
        """
        return await _call("PUT", f"borrows/{borrow_id}/pay-fine", access_token=access_token)

    @mcp.tool()
    async def get_all_borrows(
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Admin overview of all borrow records.
        Inputs:
        - page (int), limit (int): pagination.
        - status (str|None): filter by status.
        - access_token (str|None): admin token override.
        Outputs: paginated borrow list across all users.
        Behavior: GET /api/borrows; requires admin auth, auto-refresh supported.
        """
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if status:
            params["status"] = status
        return await _call("GET", "borrows", access_token=access_token, params=params)

    @mcp.tool()
    async def get_overdue_borrows(access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Admin retrieval of overdue borrow records.
        Inputs:
        - access_token (str|None): admin token override.
        Outputs: list of overdue borrows with associated metadata.
        Behavior: GET /api/borrows/overdue; admin auth required with auto-refresh retry.
        """
        return await _call("GET", "borrows/overdue", access_token=access_token)

    @mcp.tool()
    async def get_pending_borrow_requests(
        page: int = 1,
        limit: int = 20,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Admin view of pending borrow requests awaiting approval.
        Inputs:
        - page (int), limit (int): pagination controls.
        - access_token (str|None): admin token override.
        Outputs: paginated list of pending requests.
        Behavior: GET /api/borrows/pending; admin auth with auto-refresh.
        """
        params: Dict[str, Any] = {"page": page, "limit": limit}
        return await _call("GET", "borrows/pending", access_token=access_token, params=params)

    @mcp.tool()
    async def approve_borrow_request(borrow_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Approve a pending borrow request (admin action).
        Inputs:
        - borrow_id (str): request to approve.
        - access_token (str|None): admin token override.
        Outputs: updated borrow record reflecting approval.
        Behavior: PUT /api/borrows/{id}/approve; admin auth with auto-refresh.
        """
        return await _call("PUT", f"borrows/{borrow_id}/approve", access_token=access_token)

    @mcp.tool()
    async def reject_borrow_request(
        borrow_id: str,
        reason: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Reject a pending borrow request with an optional reason.
        Inputs:
        - borrow_id (str): request to reject.
        - reason (str|None): optional explanatory message.
        - access_token (str|None): admin token override.
        Outputs: updated borrow record in rejected state.
        Behavior: PUT /api/borrows/{id}/reject with JSON reason; admin auth required, auto-refresh enabled.
        """
        json_body = {"reason": reason} if reason else {}
        return await _call("PUT", f"borrows/{borrow_id}/reject", access_token=access_token, json_body=json_body)

    # ---------------- Wishlist (user) ----------------
    @mcp.tool()
    async def get_wishlist(access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Fetch the authenticated user's wishlist.
        Inputs:
        - access_token (str|None): token override; defaults to cached session.
        Outputs: array of wishlist items and any backend metadata.
        Behavior: GET /api/wishlist; requires user auth with auto-refresh.
        """
        return await _call("GET", "wishlist", access_token=access_token)

    @mcp.tool()
    async def add_to_wishlist(book_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Add a book to the user's wishlist.
        Inputs:
        - book_id (str): target book.
        - access_token (str|None): token override.
        Outputs: updated wishlist payload from backend.
        Behavior: POST /api/wishlist/add/{bookId}; requires auth, auto-refresh applied.
        """
        return await _call("POST", f"wishlist/add/{book_id}", access_token=access_token)

    @mcp.tool()
    async def remove_from_wishlist(book_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Remove a book from the user's wishlist.
        Inputs:
        - book_id (str): book to remove.
        - access_token (str|None): token override.
        Outputs: updated wishlist payload.
        Behavior: DELETE /api/wishlist/remove/{bookId}; requires auth with auto-refresh.
        """
        return await _call("DELETE", f"wishlist/remove/{book_id}", access_token=access_token)

    @mcp.tool()
    async def check_wishlist(book_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Determine if a specific book is already in the user's wishlist.
        Inputs:
        - book_id (str): book to check.
        - access_token (str|None): token override.
        Outputs: dict containing boolean flag (e.g., `inWishlist`).
        Behavior: GET /api/wishlist/check/{bookId}; requires auth, auto-refreshes on expiry.
        """
        return await _call("GET", f"wishlist/check/{book_id}", access_token=access_token)

    # ---------------- Reviews ----------------
    @mcp.tool()
    async def get_book_reviews(book_id: str, page: int = 1, limit: int = 10) -> Dict[str, Any]:
        """
        Purpose: Retrieve public reviews for a book.
        Inputs:
        - book_id (str): target book.
        - page (int), limit (int): pagination controls.
        Outputs: paginated list of reviews and metadata.
        Behavior: GET /api/reviews/book/{bookId}; public endpoint, no auth required.
        """
        params = {"page": page, "limit": limit}
        return await _call("GET", f"reviews/book/{book_id}", params=params)

    @mcp.tool()
    async def add_review(
        book_id: str,
        rating: int,
        comment: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Submit a review for a book.
        Inputs:
        - book_id (str): book being reviewed.
        - rating (int): numeric rating expected by backend.
        - comment (str|None): optional text.
        - access_token (str|None): user token override.
        Outputs: created review payload.
        Behavior: POST /api/reviews with JSON body; requires user auth, auto-refresh supported.
        """
        json_body = {"bookId": book_id, "rating": rating, "comment": comment}
        return await _call("POST", "reviews", access_token=access_token, json_body=json_body)

    @mcp.tool()
    async def update_review(
        review_id: str,
        rating: Optional[int] = None,
        comment: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Edit an existing review authored by the current user.
        Inputs:
        - review_id (str): review to update.
        - rating (int|None), comment (str|None): fields to change.
        - access_token (str|None): token override.
        Outputs: updated review payload.
        Behavior: PUT /api/reviews/{id}; requires auth, auto-refresh on expiry.
        """
        json_body: Dict[str, Any] = {}
        if rating is not None:
            json_body["rating"] = rating
        if comment is not None:
            json_body["comment"] = comment
        return await _call("PUT", f"reviews/{review_id}", access_token=access_token, json_body=json_body)

    @mcp.tool()
    async def delete_review(review_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Delete a review (owner or admin).
        Inputs:
        - review_id (str): target review.
        - access_token (str|None): token override.
        Outputs: deletion confirmation payload.
        Behavior: DELETE /api/reviews/{id}; requires auth, auto-refresh handled by helper.
        """
        return await _call("DELETE", f"reviews/{review_id}", access_token=access_token)

    @mcp.tool()
    async def get_my_review(book_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Fetch the current user's review for a specific book, if it exists.
        Inputs:
        - book_id (str): book to check.
        - access_token (str|None): token override.
        Outputs: review payload or not-found response per backend contract.
        Behavior: GET /api/reviews/my-review/{bookId}; requires auth with auto-refresh.
        """
        return await _call("GET", f"reviews/my-review/{book_id}", access_token=access_token)

    # ---------------- Admin ----------------
    @mcp.tool()
    async def get_dashboard_stats(access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Retrieve admin dashboard aggregates.
        Inputs:
        - access_token (str|None): admin token override.
        Outputs: counts, genre distribution, recent activity, most borrowed stats.
        Behavior: GET /api/admin/dashboard; admin auth required, auto-refresh enabled.
        """
        return await _call("GET", "admin/dashboard", access_token=access_token)

    @mcp.tool()
    async def get_users(
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Purpose: Admin user listing with pagination and search.
        Inputs:
        - page (int), limit (int): pagination controls.
        - search (str|None): optional query to match users.
        - access_token (str|None): admin token override.
        Outputs: paginated user list and metadata.
        Behavior: GET /api/admin/users; admin auth with auto-refresh retry.
        """
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if search:
            params["search"] = search
        return await _call("GET", "admin/users", access_token=access_token, params=params)

    @mcp.tool()
    async def get_user_details(user_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: View a single user's profile, borrow history, and fines (admin).
        Inputs:
        - user_id (str): target user.
        - access_token (str|None): admin token override.
        Outputs: user detail payload including related records.
        Behavior: GET /api/admin/users/{id}; admin auth required with auto-refresh.
        """
        return await _call("GET", f"admin/users/{user_id}", access_token=access_token)

    @mcp.tool()
    async def toggle_user_status(user_id: str, access_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Purpose: Activate/deactivate a user account (admin).
        Inputs:
        - user_id (str): target account.
        - access_token (str|None): admin token override.
        Outputs: updated user state from backend.
        Behavior: PUT /api/admin/users/{id}/toggle-status; admin auth with auto-refresh.
        """
        return await _call("PUT", f"admin/users/{user_id}/toggle-status", access_token=access_token)

    # ---------------- Images ----------------
    @mcp.tool()
    async def get_image_url(image_id: str) -> Dict[str, Any]:
        """
        Purpose: Construct a public image URL without calling the API.
        Inputs:
        - image_id (str): identifier returned by the backend.
        Outputs: { "url": "<absolute-url-to-image>" }.
        Behavior: Pure helper; uses configured base URL and does not perform HTTP requests or require auth.
        """
        base = client.base_url
        if base.endswith("/api"):
            base = base[:-4]
        return {"url": f"{base}/api/images/{image_id}"}
