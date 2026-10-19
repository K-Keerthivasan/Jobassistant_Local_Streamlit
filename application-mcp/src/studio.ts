export class Studio {
  constructor(public base = "http://127.0.0.1:8088") {
    if (base !== "http://127.0.0.1:8088")
      throw new Error("Resume Studio must use its fixed local endpoint.");
  }
  async request(route: string, body?: unknown): Promise<any> {
    const response = await fetch(this.base + route, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
      redirect: "error",
    });
    if (!response.ok)
      throw new Error(
        `Resume Studio request failed (${response.status}). Check that Studio is running and the session is valid.`,
      );
    return response.json();
  }
  get(id: string) {
    return this.request("/apply/" + encodeURIComponent(id));
  }
  /** What Studio currently says about this application's job. */
  status(id: string) {
    return this.request(
      "/application-engine/" + encodeURIComponent(id) + "/status",
    );
  }
  appliedByMe(jobKey: string, note = "") {
    return this.request(
      "/application-engine/jobs/" + encodeURIComponent(jobKey) + "/applied-by-me",
      { note },
    );
  }
  validate(id: string) {
    return this.request(
      "/application-engine/" + encodeURIComponent(id) + "/validate",
    );
  }
  snapshot(id: string, data: unknown) {
    return this.request(
      "/application-engine/" + encodeURIComponent(id) + "/snapshot",
      data,
    );
  }
  confirm(id: string) {
    return this.request("/apply/" + encodeURIComponent(id) + "/confirm", {
      approved: true,
      submit_by: "agent",
      note: "User approved this exact application from the engine review screen.",
    });
  }
  result(id: string, status: string, note: string, success: boolean, submittedBy: "agent" | "me" = "agent") {
    return this.request("/apply/" + encodeURIComponent(id) + "/log", {
      status,
      note,
      verified_success: success,
      submitted_by: submittedBy,
    });
  }
}
