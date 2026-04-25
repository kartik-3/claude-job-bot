import json
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from db import STATUSES, get_connection


def jobs_list(request: object) -> JsonResponse:
    status = request.GET.get("status")
    company = request.GET.get("company")
    ats = request.GET.get("ats")
    search = request.GET.get("search")

    query = "SELECT * FROM jobs WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if company:
        query += " AND company = ?"
        params.append(company)
    if ats:
        query += " AND ats = ?"
        params.append(ats)
    if search:
        query += " AND (title LIKE ? OR company LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY COALESCE(fit_score, -1) DESC, company, title"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return JsonResponse([dict(r) for r in rows], safe=False)


@csrf_exempt
@require_http_methods(["PATCH"])
def job_update(request: object, job_id: str) -> JsonResponse:
    data = json.loads(request.body)
    new_status = data.get("status")
    if new_status not in STATUSES:
        return JsonResponse({"error": f"Invalid status: {new_status}"}, status=400)

    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        if new_status == "applied":
            conn.execute(
                "UPDATE jobs SET status = ?, applied_at = ? WHERE id = ?",
                (new_status, now, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?",
                (new_status, job_id),
            )
    return JsonResponse({"ok": True})
