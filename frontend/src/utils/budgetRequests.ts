/** Badge class for a budget request status. */
export function statusBadgeClass(status: string): string {
  if (status === "approved") return "dash-badge dash-badge-success";
  if (status === "rejected") return "dash-badge dash-badge-danger";
  return "dash-badge dash-badge-warning";
}
