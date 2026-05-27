"use client";

import { useParams } from "next/navigation";
import { AccretionTheater } from "@/components/accretion/accretion-theater";

export default function AccretionTheaterPage() {
  const params = useParams();
  const execId = params.id as string;
  return <AccretionTheater execId={execId} />;
}
