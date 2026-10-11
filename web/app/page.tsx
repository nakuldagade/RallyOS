"use client";

// "/" is only a doorway: a logged-in visitor goes to their own dashboard, anyone else to the login page.
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor, useAuth } from "@/lib/auth";
import { Loading } from "@/components/ui";

export default function Root() {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (ready) router.replace(homeFor(user));
  }, [ready, user, router]);
  return <Loading />;
}
