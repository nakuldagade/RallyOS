"use client";

// The Sketchfab venue model for a sport, picked from the sport the analysis detected. An embedded model cannot take our data, so
// shot paths, players and heatmaps are drawn in the 3D court tab instead; this is the picture of a real venue to look around.
import { sportLabel } from "@/lib/sports";

interface Model {
  uid: string;
  title: string;
  author: string;
  authorUrl: string;
  slug: string;
  note?: string;
}

export const VENUE_MODELS: Record<string, Model> = {
  tennis: { uid: "0ad5af25f6084d3f820c3f8dc36c58e8", title: "Tennis Court (PBR)", author: "Tiko", authorUrl: "https://sketchfab.com/tikoavp", slug: "tennis-court-pbr" },
  badminton: { uid: "2494874f122142c79e6bfabd930fc291", title: "Badminton Court", author: "JG3D", authorUrl: "https://sketchfab.com/jg-3d", slug: "badminton-court" },
  table_tennis: { uid: "457c34c9297d44a1a5d4e5d093c6a712", title: "Table Tennis Table", author: "Diccbudd", authorUrl: "https://sketchfab.com/Diccbudd", slug: "table-tennis-table" },
  squash: {
    uid: "3599c6a7af40430e9f568a80880f78c3", title: "Ball Games - Ultimate Sport Package", author: "1Poly", authorUrl: "https://sketchfab.com/1poly", slug: "ball-games-ultimate-sport-package",
    note: "This is a package of many courts. The squash court is the white block with the pale-blue top near the middle of the scene, just below the white ice rink: orbit and zoom to it. (The viewer's scripting interface did not start in our test, so the page cannot zoom to it for you.)",
  },
  pickleball: { uid: "1cf9e0f44b0f49aca0484b3d986c5e8d", title: "Pickleball Court - Fully Textured", author: "Marc Sawyer", authorUrl: "https://sketchfab.com/whitewashstudio", slug: "pickleball-court-fully-textured" },
  padel: { uid: "a2028f2809674091b35dc03191a92b06", title: "Tennis Padel Galis Split", author: "Sergo_CRAFTSMAN", authorUrl: "https://sketchfab.com/Sergo_CRAFTSMAN", slug: "tennis-padel-galis-split" },
};

export default function VenueModel({ sport }: { sport: string }) {
  const m = VENUE_MODELS[sport] ?? VENUE_MODELS.tennis;
  return (
    <div>
      <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
        <iframe title={m.title} className="h-full w-full" frameBorder={0} allowFullScreen allow="autoplay; fullscreen; xr-spatial-tracking"
          src={`https://sketchfab.com/models/${m.uid}/embed`} />
      </div>
      <p className="mt-2 text-xs text-muted">
        {sportLabel(VENUE_MODELS[sport] ? sport : "tennis")} venue model (it needs internet). Our shot paths, players and heatmaps are not drawn inside it: an embedded model cannot take our data, so the 3D court tab builds the court from the
        sport&apos;s own measurements instead, which keeps every position exact.
        {m.note ? ` ${m.note}` : ""}
        {" "}Model: <a className="text-accent" href={`https://sketchfab.com/3d-models/${m.slug}-${m.uid}`} target="_blank" rel="nofollow noreferrer">{m.title}</a> by{" "}
        <a className="text-accent" href={m.authorUrl} target="_blank" rel="nofollow noreferrer">{m.author}</a> on{" "}
        <a className="text-accent" href="https://sketchfab.com" target="_blank" rel="nofollow noreferrer">Sketchfab</a>.
      </p>
    </div>
  );
}
