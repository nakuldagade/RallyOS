import { API } from "@/lib/api";
import { Card, PageHeader } from "@/components/ui";

const SDK = `from rallyos import Analyzer
m = Analyzer(sport="auto").run("match.mp4", out_dir="out/")
print(m.sport, m.score, m.rallies[0].hits)`;

const SCORING = `from rallyos.rules import engine_for

eng = engine_for("table_tennis")       # rules come from sports/table_tennis.yaml
eng.play([0, 1] * 10 + [0, 0])         # 12-10
print(eng.snapshot()["games"])          # [[12, 10]]`;

const CURL = (api: string) => `curl ${api}/v1/matches/m_001
curl ${api}/v1/matches/m_001/report
curl "${api}/v1/predict?a=p_anika&b=p_kabir"
curl -F video=@match.mp4 -F sport=auto ${api}/v1/videos`;

function Code({ children }: { children: string }) {
  return <pre className="overflow-auto rounded-lg bg-fg/5 p-3 text-xs leading-relaxed">{children}</pre>;
}

export default function DevelopersPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <PageHeader title="Developers" subtitle="The vision core is a pip-installable SDK; the REST API is a thin layer on top."
        actions={<a href={`${API}/docs`} target="_blank" rel="noreferrer" className="btn-primary">Open API docs ↗</a>} />
      <Card title="Python SDK (pip install -e core/)"><Code>{SDK}</Code><p className="mt-2 text-xs text-muted">The pipeline stages are being built; the scoring engine below works today.</p></Card>
      <Card title="Scoring engine: any sport from YAML"><Code>{SCORING}</Code></Card>
      <Card title="REST API"><Code>{CURL(API)}</Code></Card>
      <Card title="Add a sport">
        <p className="text-sm text-muted">
          POST a YAML with <code>sport</code>, <code>court</code>, <code>projectile</code> and <code>scoring</code> to <code>/v1/sports</code>.
          The scoring block is checked against the generic engine (rally_point, side_out or game_set). No code changes, no training.
        </p>
      </Card>
    </div>
  );
}
