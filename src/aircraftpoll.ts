/**
 * Aircraft polling with the live range (1.0.7). Pure logic, unit-tested with node.
 *
 * 1.0.6 asked /api/aircraft without a range, so after a range change the server
 * kept fetching the old radius until the debounced config save landed, and a
 * slow reply from before the change could land after a newer one. Each poll
 * now names the range on the glass, and replies are only used when they are
 * the newest and were asked for the current range.
 */
export function aircraftUrl(rangeNm: number, freeze: boolean): string {
  const params = new URLSearchParams();
  if (Number.isFinite(rangeNm) && rangeNm > 0) params.set("range", String(Math.round(rangeNm * 10) / 10));
  if (freeze) params.set("freeze", "1");
  const query = params.toString();
  return `/api/aircraft${query ? `?${query}` : ""}`;
}

export interface PollTicket {
  seq: number;
  epoch: number;
}

export class PollGate {
  private seq = 0;
  private applied = 0;
  private epoch = 0;

  /** Call before each request. */
  begin(): PollTicket {
    this.seq += 1;
    return { seq: this.seq, epoch: this.epoch };
  }

  /** The range (or anything the request depends on) changed: older requests are stale. */
  invalidate(): void {
    this.epoch += 1;
  }

  /** True when this reply is newer than the last one used and still for the current range. */
  accept(ticket: PollTicket): boolean {
    if (ticket.epoch !== this.epoch || ticket.seq <= this.applied) return false;
    this.applied = ticket.seq;
    return true;
  }
}
