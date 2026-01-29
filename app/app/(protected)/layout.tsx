import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AUTH_COOKIE_NAME, verifyAuthToken } from "@/lib/auth";

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (!token) {
    redirect("/login");
  }

  let isValid = false;
  try {
    isValid = Boolean(await verifyAuthToken(token));
  } catch {
    isValid = false;
  }

  if (!isValid) {
    redirect("/login");
  }

  return children;
}
