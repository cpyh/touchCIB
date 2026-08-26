export const riskNames: Record<string, string> = {
  R1: "保守型",
  R2: "稳健型",
  R3: "平衡型",
  R4: "成长型",
  R5: "进取型",
};

export const channelNames: Record<string, string> = {
  sms: "短信",
  call: "电话",
  app_push: "App推送",
  manager: "客户经理",
};

export function PageHead({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

export function Status({
  children,
  warn = false,
}: {
  children: React.ReactNode;
  warn?: boolean;
}) {
  return (
    <span className={warn ? "status warn" : "status"}>
      <i />
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  note,
  gold = false,
}: {
  label: string;
  value: string;
  note: string;
  gold?: boolean;
}) {
  return (
    <div className={gold ? "metric gold" : "metric"}>
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{note}</span>
    </div>
  );
}

export function Table({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="table">
      <table>
        <thead>
          <tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Timeline({ items }: { items: string[][] }) {
  return (
    <div className="timeline">
      {items.map((item, index) => (
        <div key={index}>
          <b>{item[0]}</b>
          <span>{item[1]}</span>
          <p>{item[2]}</p>
        </div>
      ))}
    </div>
  );
}
