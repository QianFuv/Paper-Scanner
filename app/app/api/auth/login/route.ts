import { NextResponse, type NextRequest } from "next/server";
import {
  AUTH_COOKIE_NAME,
  createAuthToken,
  getAuthTokens,
  getExpiryMillis,
  verifyToken,
} from "@/lib/auth";

type LoginPayload = {
  token?: string;
};

export async function POST(request: NextRequest) {
  let tokens: string[];
  try {
    tokens = await getAuthTokens();
  } catch (error) {
    return NextResponse.json(
      { message: "Authentication is not configured" },
      { status: 500 },
    );
  }
  if (tokens.length === 0) {
    return NextResponse.json(
      { message: "Authentication is not configured" },
      { status: 500 },
    );
  }

  const body = (await request.json()) as LoginPayload;
  const token = (body.token ?? "").trim();

  if (!token || !(await verifyToken(token))) {
    return NextResponse.json(
      { message: "Invalid token" },
      { status: 401 },
    );
  }

  const authToken = await createAuthToken(token);
  const response = NextResponse.json({ ok: true });
  const maxAge = Math.floor((await getExpiryMillis()) / 1000);

  response.cookies.set({
    name: AUTH_COOKIE_NAME,
    value: authToken,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  });

  return response;
}
