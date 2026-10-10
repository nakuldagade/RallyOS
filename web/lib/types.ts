// TypeScript types matching match.json (AGENTS.md §11.3). Keep in sync with api/schemas.py.

export type XY = [number, number];

export interface VideoInfo {
  src: string;
  overlay?: string | null;
  fps: number;
  width: number;
  height: number;
  duration_s: number;
  sha256?: string | null;
}

export interface Calibration {
  method: string;
  homography: number[][]; // image px -> court metres
  focal_px?: number | null;
  reprojection_error_px?: number | null;
  camera_position_m?: [number, number, number] | null; // from self-calibration (x, y, height)
  note?: string | null;                                // why no automatic calibration was applied
  auto?: { sport: string; sport_confidence: number; fit_score: number; precision: number; recall: number; quality: string } | null;
}

export interface PlayerRef {
  track_id: number;
  player_id?: string | null;
  name: string;
  side?: string | null;
  color?: string | null;
}

export interface Rally {
  idx: number;
  t_start: number;
  t_end: number;
  hits: number;
  winner_track_id?: number | null;
  end_reason?: string | null;
  confidence: number;
  score_after?: string | null;
  winner_confidence?: number | null; // suggested winner (from the landing + call); a human confirms
  hitter_conflict?: boolean;         // last detected hitter disagrees with the landing side
}

export interface MatchEvent {
  id: string;
  rally_idx: number;
  t: number;
  type: string; // hit | landing | bounce | ...
  track_id?: number | null;
  px?: XY | null;
  court?: XY | null;
  shot?: string | null;
  speed_kmh?: number | null;
  speed_err_pct?: number | null;
  speed_basis?: string;      // "hit-to-hit" | "hit-to-landing": which two points the average was taken between
  speed_why_not?: string;    // why no speed was given
  confidence: number;
  source?: string[];
  t_audio?: number;          // onset time heard at the microphone (s)
  sound_delay_ms?: number;   // speed-of-sound correction applied
  hitter_inferred?: boolean; // hitter from alternation, not from a wrist
  call?: string;
  call_prob?: number;
  p_in?: number;
  margin_m?: number;  // distance to the nearest in-bounds line (+ inside, - outside)
  note?: string;      // why no call was made
  ellipse_m?: [number, number, number]; // semi-axis a, semi-axis b (m), angle (deg)
  dispute_id?: string;
  interpolated?: boolean;
}

export interface RatingChange {
  player_id: string;
  before: number;
  after: number;
  rd: number;
  evidence_level: string;
}

export interface Score {
  games: number[][];
  winner_track_id?: number | null;
  confirmed_by_human?: boolean;
  rating_update?: RatingChange[];
  score_str?: string;
  source?: string | null;        // "suggested from line calls"
  unresolved_rallies?: number;   // rallies with no suggested winner (not counted)
  from_clip_start?: boolean;     // points counted from 0-0 at the start of the clip
}

export interface PlayerStats {
  distance_m?: number;
  avg_return_to_base_s?: number;
  split_step_pct?: number;
  shot_mix?: Record<string, number>;
  avg_smash_kmh?: number;
  heatmap_url?: string;
  zone_pct?: Record<string, number>; // share of tracked time per zone of the own half
  most_zone?: string;                // e.g. "rear-left" (player's point of view)
  most_zone_pct?: number;
  [k: string]: unknown;
}

export interface Dispute {
  id: string;
  event_id: string;
  clip_url?: string | null;
  call: string;
  prob: number;
  status: string;
}

export interface Insight {
  text: string;
  stat_ids: string[];
  clip_t: number[];
  player_track_id?: number | null;
  grounded?: boolean;
}

export interface AudioStats {
  status: string; // "ok" | "no audio track" | ...
  onsets: number;
  matched: number;
  audio_only: number;
  vision_only: number;
  av_offset_s: number;
  sound_delay_corrected: boolean;
  mean_sound_delay_ms?: number | null;
  method?: string;
}

export interface BallStats {
  tracker: string; // "racketvision" | "geometric"
  model?: string;
  checkpoint?: string;
  frames: number;
  detected_frames: number;
  detected_pct: number;
  interpolated_frames: number;
  longest_gap_s: number;
  mean_conf?: number | null;
  hit_candidates?: number;
  reference_metrics?: Record<string, number>;
  reference_note?: string;
  source_csv?: string;
}

export interface MatchJSON {
  schema_version: string;
  match_id: string;
  title?: string | null;
  sport: string;
  sport_confidence?: number | null;
  video: VideoInfo;
  calibration: Calibration;
  players: PlayerRef[];
  tracks_url?: string | null;
  rallies: Rally[];
  events: MatchEvent[];
  score: Score;
  stats: {
    per_player?: Record<string, PlayerStats>;
    match?: Record<string, number>;
    ball?: BallStats;
    audio?: AudioStats;
    pipeline?: {
      device?: string;
      processing_s?: number;
      players_backend?: string | null;
      players_skipped_reason?: string | null;
      not_computed?: string[];
      static_people_ignored?: { head_px: [number, number]; frames_pct: number }[];
      ignored_detections?: Record<string, number>;
    };
  };
  disputes: Dispute[];
  insights: Insight[];
}

export interface TrackPlayer {
  track_id: number;
  bbox: [number, number, number, number];
  court: XY | null;
  kp?: [number, number, number][];
}

export interface TrackBall {
  px: XY;
  court: XY | null;
  conf: number;
  interp: boolean;
}

export interface IgnoredPerson {
  bbox: [number, number, number, number];
  reason: string;
}

export interface TrackFrame {
  f: number;
  players: TrackPlayer[];
  others?: IgnoredPerson[]; // people detected but not counted as players (officials, spectators)
  ball: TrackBall | null;
}

export interface Tracks {
  fps: number;
  frames: TrackFrame[];
}

export interface MatchSummary {
  match_id: string;
  title?: string | null;
  ball_tracker?: string | null;
  sport: string;
  status: string;
  players: string[];
  games: number[][];
  winner_track_id?: number | null;
  confirmed_by_human: boolean;
  evidence_level: string;
  duration_s?: number | null;
  rallies: number;
  sha256?: string | null;
}

export interface Player {
  id: string;
  name: string;
  sport: string;
  rating: number;
  rd: number;
  vol: number;
  style_vec?: number[] | null;
  lat?: number | null;
  lng?: number | null;
}

export interface RatingPoint {
  id?: number;
  rating: number;
  rd: number;
  at: string;
  match_id?: string | null;
  evidence_level: string;
}

export interface Suggestion {
  player_id: string;
  name: string;
  rating: number;
  distance_km: number;
  style_similarity: number;
  style_complement: number;
  score: number;
}

export interface Factor {
  factor: string;
  value: number | string;
  contribution: number;
  explanation: string;
}

export interface Prediction {
  a: string;
  b: string;
  p_a_wins: number;
  factors: Factor[];
}

export interface CoachReport {
  match_id: string;
  source: "pipeline" | "claude" | "template";
  insights: Insight[];
  note?: string | null;
}

export interface DisputeDetail extends Dispute {
  match_id: string;
  event: MatchEvent | null;
  sha256?: string | null;
}

export interface CourtLine {
  id: string;
  p1: XY;
  p2: XY;
}

export interface SportConfig {
  sport: string;
  display_name?: string;
  court: {
    length: number;
    width: number;
    lines: CourtLine[];
    base_position?: XY;
    fingerprint_lines?: string[];
    zones?: Record<string, { y_from_net_m?: [number, number] }>;
  };
  net?: { height_center?: number; height_post?: number } | null;
  projectile: { kind: string; size_m: number; bounces?: boolean; motion_model?: string; wall_rebounds?: boolean };
  scoring: { type: string; [k: string]: unknown };
  events?: string[];
  capture?: { min_fps?: number; recommended_fps?: number; camera?: string };
  yaml?: string;
}

export interface Venue {
  id: number;
  name: string;
  city: string;
  lat: number;
  lng: number;
}

export interface Court {
  id: number;
  venue_id: number;
  sport: string;
  smart_court: boolean;
}

export interface CourtRow {
  court: Court;
  venue: Venue;
  distance_km?: number;
}

export interface Booking {
  id: number;
  court_id: number;
  player_id: string;
  slot_start: string;
  slot_end: string;
  status: string;
}

export interface Tournament {
  id: number;
  name: string;
  sport: string;
  start_date?: string | null;
  status: string;
}

export interface DrawMatch {
  id: number;
  tournament_id: number;
  round: number;
  slot: number;
  p1?: string | null;
  p2?: string | null;
}

export interface JobStage {
  id: string;
  label: string;
  state: "pending" | "active" | "done" | "skipped" | "failed";
  frac: number;          // 0..1 within this stage
  note: string | null;   // what it is doing, or why it was skipped
  seconds: number | null;
}

export interface CourtDetection {
  found: boolean;
  method?: string;
  message?: string;
  sport?: string;
  sport_confidence?: number;
  quality?: "high" | "check";
  fit_score?: number;
  precision?: number;
  recall?: number;
  corners_px?: [number, number][];   // near-left, near-right, far-right, far-left (frame pixels)
  width?: number;
  height?: number;
  ranking?: [string, number][];
  focal_px?: number | null;
  camera_position_m?: [number, number, number] | null;
}

export interface Job {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  stages?: JobStage[];
  note?: string | null;  // e.g. queued behind another analysis
  progress: number;
  match_id: string | null;
  error: string | null;
  simulated: boolean;
  skipped?: string[];
  calibrated?: boolean;
  started?: number;
}

export interface Health {
  ok: boolean;
  mock_fallback: boolean;
  coach: string;
}
