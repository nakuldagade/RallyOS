// SVG top-down court drawn from the sport YAML (metres). Near baseline at the bottom.
import type { SportConfig } from "@/lib/types";
import type { HeatGrid } from "@/lib/sports";

export interface CourtDot {
  x: number;
  y: number;
  color: string;
  label?: string;
  hollow?: boolean;
  onClick?: () => void;
  title?: string;
}

export interface CourtEllipse {
  x: number;
  y: number;
  a: number;
  b: number;
  angle: number;
  color: string;
}

interface Props {
  sport: Pick<SportConfig, "court">;
  dots?: CourtDot[];
  ellipse?: CourtEllipse | null;
  heat?: HeatGrid | null;
  focus?: { x: number; y: number; r: number } | null;
  highlightLines?: string[];
  className?: string;
}

export default function MiniCourt({ sport, dots = [], ellipse, heat, focus, highlightLines = [], className = "" }: Props) {
  const { length: L, width: W, lines } = sport.court;
  const span = focus ? focus.r * 2 : Math.max(L, W);
  const pad = Math.max(L, W) * 0.06;
  const sy = (y: number) => L - y;
  const viewBox = focus
    ? [focus.x - focus.r, sy(focus.y) - focus.r, 2 * focus.r, 2 * focus.r]
    : [-pad, -pad, W + 2 * pad, L + 2 * pad];
  const r = span * 0.022;

  return (
    <svg viewBox={viewBox.join(" ")} className={className} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Top-down court view">
      <rect x={-L} y={-L} width={W + 2 * L} height={3 * L} fill="rgb(var(--court-out))" />
      <rect x={0} y={0} width={W} height={L} fill="rgb(var(--court))" />
      {heat?.grid.map((row, i) =>
        row.map((v, j) =>
          v > 0.02 ? (
            <rect key={`${i}-${j}`} x={j * heat.cell} y={sy((i + 1) * heat.cell)} width={heat.cell} height={heat.cell}
              fill="#f59e0b" opacity={0.12 + 0.68 * v} />
          ) : null,
        ),
      )}
      {lines.map((l) => {
        const isNet = l.id === "net";
        const hi = highlightLines.includes(l.id);
        return (
          <line key={l.id} x1={l.p1[0]} y1={sy(l.p1[1])} x2={l.p2[0]} y2={sy(l.p2[1])}
            stroke={hi ? "#facc15" : isNet ? "#cbd5e1" : "white"} strokeWidth={hi ? 3 : isNet ? 2.5 : 1.4}
            strokeDasharray={isNet ? "5 3" : undefined} vectorEffect="non-scaling-stroke" opacity={0.92} />
        );
      })}
      {ellipse && (
        <g>
          <ellipse cx={ellipse.x} cy={sy(ellipse.y)} rx={ellipse.a} ry={ellipse.b}
            transform={`rotate(${-ellipse.angle} ${ellipse.x} ${sy(ellipse.y)})`}
            fill={ellipse.color} fillOpacity={0.25} stroke={ellipse.color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        </g>
      )}
      {dots.map((d, i) => (
        <g key={i} onClick={d.onClick} className={d.onClick ? "cursor-pointer" : undefined}>
          {d.title && <title>{d.title}</title>}
          <circle cx={d.x} cy={sy(d.y)} r={r} fill={d.hollow ? "none" : d.color} stroke={d.hollow ? d.color : "white"}
            strokeWidth={d.hollow ? 2 : 1.2} vectorEffect="non-scaling-stroke" />
          {d.label && (
            <text x={d.x} y={sy(d.y) - r * 1.7} fontSize={r * 1.9} textAnchor="middle" fill="white"
              style={{ paintOrder: "stroke", stroke: "rgba(0,0,0,0.6)", strokeWidth: r * 0.4 }}>
              {d.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
