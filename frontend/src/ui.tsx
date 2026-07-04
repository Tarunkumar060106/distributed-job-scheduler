import { STATUS_COLORS } from "./api";

export function Badge({ status, label }: { status: string; label?: string }) {
  const color = STATUS_COLORS[status] ?? "#57534e";
  return (
    <span className="badge" style={{ ["--badge-color" as any]: color }}>
      {(label ?? status).replace("_", " ")}
    </span>
  );
}

export function PageHead({ title, sub, right }: {
  title: string; sub?: string; right?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>{title}</h2>
        {right}
      </div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}
