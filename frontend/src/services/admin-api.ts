import type { InterviewListResponse, InterviewDetail } from "@/types/admin";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ADMIN_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY ?? "change-me-admin-key";

class AdminApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public detail?: string
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

async function adminRequest<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Key": ADMIN_KEY,
    },
  });

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error;
    } catch {
      detail = res.statusText;
    }
    throw new AdminApiError(`HTTP ${res.status}`, res.status, detail);
  }

  return res.json() as Promise<T>;
}

export async function listInterviews(
  page: number = 1,
  limit: number = 20
): Promise<InterviewListResponse> {
  return adminRequest<InterviewListResponse>(
    `/api/v1/admin/interviews?page=${page}&limit=${limit}`
  );
}

export async function getInterviewDetail(
  sessionId: string
): Promise<InterviewDetail> {
  return adminRequest<InterviewDetail>(
    `/api/v1/admin/interviews/${sessionId}`
  );
}

export { AdminApiError };
