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
  cdn_src?: string | null;       // the same video on Cloudinary, when live mode used cloud storage
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
  shot_conf?: number | null;
  shot_why?: string;                  // one sentence: why this label, or why none
  shot_unchecked?: string[];          // rule conditions that could not be measured (e.g. descent_deg_min)
  speed_kmh?: number | null;
  speed_err_pct?: number | null;
  shot_rating?: { outcome: string; technique: number | null; score: number; parts: Record<string, number>; confidence: number; why: string };
  speed_basis?: string;      // "hit-to-hit" | "hit-to-landing": which two points the flight was measured between
  speed_kind?: "launch" | "average";   // launch = speed at the racket from distance, time and air drag (shuttle); average = horizontal average over the flight
  avg_speed_kmh?: number | null;       // the plain distance / time, kept for reference
  launch_angle_deg?: number | null;
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
  pulled_away_n?: number;            // own shots that pulled the player away from base
  stayed_central_n?: number;         // own shots hit from base (not in the recovery average)
  returned_pct?: number;             // of the pulled-away shots, how often back at base before the reply
  slowest_return_t?: number[];
  split_step_n?: number;             // opponent shots that could be judged
  split_step_detected?: number;
  split_step_clip_t?: number[];
  fastest_shot_kmh?: number;
  fastest_shot_err_pct?: number;     // 1-sigma band of the fastest shot (launch speed); absent in older match files (then an average)
  fastest_shot_t?: number;
  best_shot?: BestShot;              // outcome first (won the point > forced an error > kept the rally going > not seen > lost the point), technique inside it
  best_shots?: BestShot[];
  avg_shot_kmh?: number;
  fatigue?: {
    enough_data: boolean; n_shots: number; note?: string;
    first_third_return_s?: number; last_third_return_s?: number; return_change_pct?: number | null;
    speed_change_pct?: number;
  };
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

/** Present when the match was recorded live (schema 1.1): how the continuous capture behaved. All numbers are measured, not targets. */
export interface LiveBlock {
  session_id: string;
  chunk_seconds: number;
  chunks: number;
  avg_latency_s?: number;
  max_lag_s?: number;
  dropped_frames?: number;
  reduced_quality_chunks?: number;
  avg_process_s?: number;
  finalise_s?: number;
  cdn?: { provider: string; uploaded: boolean; error?: string };
}

export interface BestShot {
  t: number;
  shot: string | null;
  outcome: "winner" | "forced_error" | "kept_going" | "unknown" | "error";
  score: number;                     // 0-100: the outcome sets the band (winner 80-100 ... lost 0-20), the technique places the shot inside it
  technique: number | null;          // 0-1, null when too little was measured
  confidence: number;
  why: string;
  basis?: string;                    // "outcome" or "technique only: ..."
}

/** The best shot of the whole match as an ~8 s clip (match.json "highlight"); absent when no shot could be rated. */
export interface Highlight {
  clip_url: string;
  clip_start: number;
  clip_end: number;
  duration_s: number;
  track_id: number;
  t: number;                         // when the shot was hit, in the full video
  shot: string | null;
  score: number;
  outcome: "winner" | "forced_error" | "kept_going" | "unknown" | "error";
  technique: number | null;
  confidence: number;
  why: string;
  basis: string;                     // "outcome" or "technique only: ..."
}

export interface HighlightItem {
  match_id: string;
  date: string;
  sport: string | null;
  duration_s: number | null;
  players: (string | null)[];
  best_player: string | null;
  highlight: Highlight;
}

export interface MatchJSON {
  schema_version: string;
  match_id: string;
  title?: string | null;
  sport: string;
  sport_confidence?: number | null;
  video: VideoInfo;
  live?: LiveBlock | null;
  highlight?: Highlight | null;
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
    shots?: { labelled: number; unlabelled: number; why_unlabelled?: Record<string, number>; rules_that_need_bounce_or_wall_data?: string[]; apex?: string } | null;
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
  net?: { height_center?: number; height_post?: number; overhang_m?: number } | null;
  walls?: { id: string; plane: string; height_m?: number; material?: string; y_range?: [number, number]; out_line_m?: number; out_line_from_m?: number; out_line_to_m?: number; lines?: { id: string; p1: [number, number]; p2: [number, number] }[] }[];
  view3d?: { surface?: { out: string; inner: string; line: string }; plane_height_m?: number; legs?: boolean; wall_color?: string; wall_opacity?: number };
  projectile: { kind: string; size_m: number; bounces?: boolean; motion_model?: string; wall_rebounds?: boolean; terminal_velocity_mps?: number; max_height_m?: number; speed_range_kmh?: [number, number] };
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

/** What calibration and detection found (stage_court.json), available the moment the court stage ends. */
export interface CourtSummary {
  sport: string;
  sport_given: boolean;
  sport_confidence: number | null;
  sport_source: string;
  calibrated: boolean;
  method: string | null;
  quality: string | null;
  reprojection_error_px: number | null;
  focal_px: number | null;
  camera_position_m: number[] | null;
  corners_px: [number, number][] | null;
  precision: number | null;
  note: string | null;
  video: { fps: number; width: number; height: number };
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
  detected?: CourtSummary;      // the court and sport found by calibration, present as soon as that stage is over
}

export interface Health {
  ok: boolean;
  mock_fallback: boolean;
  coach: string;
}


// ---- accounts, a player's history and analysis, the coach dashboard -------------------------------------------------
export interface AuthUser {
  id: number;
  email: string;
  name: string;
  role: "player" | "coach";
  player_id: string | null;
}

export interface MetricValues {
  avg_return_to_base_s: number | null;
  returned_pct: number | null;
  split_step_pct: number | null;
  fastest_shot_kmh: number | null;
  top_speed_mps: number | null;
  distance_per_min: number | null;
  best_shot_score: number | null;
}

export interface AnalysisMatch {
  match_id: string;
  date: string;
  sport: string;
  duration_s: number;
  side: string | null;
  opponent: string;
  opponent_id: string | null;
  result: "won" | "lost" | null;
  hits: number | null;
  distance_m: number | null;
  metrics: MetricValues;
  shot_mix: Record<string, number>;
  best_shot: BestShot | null;
}

export interface Comparison {
  metric: keyof MetricValues;
  label: string;
  unit: string;
  better: "lower" | "higher" | "neutral";
  earlier: number;
  latest: number;
  delta: number;
  change_pct: number;
  verdict: "better" | "worse" | "steady" | "changed";
  n_earlier: number;
}

export interface PlayerAnalysis {
  player: { id: string; name: string; sport: string; rating: number; rd: number };
  summary: { matches: number; analysed_minutes: number; hits: number; distance_m: number; wins: number; losses: number; frames_tracked: number };
  matches: AnalysisMatch[];
  trends: Record<string, { match_id: string; i: number; value: number | null }[]>;
  compare: Comparison[];
  insights: { metric: string; verdict: string; text: string }[];
  heatmap: { cell: number; sport: string; court: { length: number; width: number }; frames: number; all: number[][] | null; earlier: number[][] | null; latest: number[][] | null };
  zones: Record<string, number>;
  shot_mix: Record<string, number>;
  best_shots: (BestShot & { match_id: string; date: string })[];
  data_note: string;
}

export interface CoachRow {
  player_id: string;
  name: string;
  rating: number;
  rd: number;
  rating_change: number | null;
  rating_is_sample: boolean;
  matches: number;
  analysed_minutes: number;
  latest: { match_id: string; opponent: string; result: string | null; date: string; metrics: MetricValues } | null;
  attention: { metric: string; text: string }[];
  improving: { metric: string; text: string }[];
}

export interface CoachDashboard {
  coach: { id: number; name: string };
  players: CoachRow[];
  totals: { players: number; matches: number; need_attention: number };
}
