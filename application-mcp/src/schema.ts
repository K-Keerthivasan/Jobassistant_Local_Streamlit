import { z } from "zod";

export const Field = z.object({
  frameId: z.number().int().default(0),
  selector: z.string(),
  label: z.string(),
  type: z.string(),
  required: z.boolean(),
  value: z.string().default(""),
  options: z.array(z.string()).default([]),
  files: z.array(z.string()).default([]),
  accept: z.string().default(""),
  invalid: z.boolean().default(false),
});
export type Field = z.infer<typeof Field>;
export const Snapshot = z.object({
  url: z.string(),
  title: z.string(),
  fields: z.array(Field),
  buttons: z.array(
    z.object({
      frameId: z.number(),
      selector: z.string(),
      label: z.string(),
      href: z.string().optional(),
    }),
  ),
  blockers: z.array(z.string()),
  confirmation: z.string().default(""),
});
export type Snapshot = z.infer<typeof Snapshot>;
export const ApplyInput = z.object({
  jobUrl: z.url(),
  resumePath: z.string(),
  coverLetterPath: z.string().nullable().optional(),
  profileId: z.literal("default").default("default"),
  mode: z.enum(["review", "assisted", "automatic"]).default("review"),
  company: z.string().min(1),
  title: z.string().min(1),
  studioSessionId: z.string().min(1),
  allowedDomains: z.array(z.string()).default([]),
});
export type ApplyInput = z.infer<typeof ApplyInput>;
export const State = z.enum([
  "opening",
  "working",
  "paused",
  "review",
  "submitting",
  "uncertain",
  "submitted",
  "failed",
  "rejected",
]);
export type State = z.infer<typeof State>;
export const ApplicationSchema = z.object({
  id: z.string(),
  input: ApplyInput,
  state: State,
  ats: z.string(),
  snapshot: Snapshot.optional(),
  documents: z.array(
    z.object({
      kind: z.string(),
      path: z.string(),
      hash: z.string(),
      name: z.string(),
      attached: z.boolean(),
      frameId: z.number().optional(),
      selector: z.string().optional(),
      omissionReason: z.string().optional(),
    }),
  ),
  filled: z.array(
    z.object({ label: z.string(), value: z.string(), source: z.string() }),
  ),
  reason: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  reviewHash: z.string().optional(),
  approvedHash: z.string().optional(),
  approvedAt: z.string().optional(),
  confirmation: z.string().optional(),
  synced: z.boolean().optional(),
  evidence: z
    .array(
      z.object({
        kind: z.string(),
        path: z.string(),
        url: z.string(),
        at: z.string(),
      }),
    )
    .optional(),
});
export type Application = z.infer<typeof ApplicationSchema>;
export const MappingSchema = z.object({
  label: z.string(),
  type: z.string(),
  options: z.array(z.string()),
  profilePath: z.string(),
});
const EventSchema = z.object({
  at: z.string(),
  kind: z.string(),
  data: z.string(),
});
export function outputSchema(name: string) {
  const result =
    name === "detect_ats"
      ? z.object({
          ats: z.string(),
          adapters: z.array(
            z.object({ name: z.string(), tested: z.boolean() }),
          ),
        })
      : name === "stop_applications"
        ? z.object({ stopped: z.boolean() })
        : name === "update_answer_bank" ||
            name === "update_confirmed_profile_fact"
          ? z.object({ saved: z.boolean(), reason: z.string().optional() })
          : name === "confirm_site_field_mapping"
            ? z.array(MappingSchema)
            : name === "get_application_history"
              ? z.union([
                  z.array(ApplicationSchema),
                  z.object({
                    application: ApplicationSchema,
                    events: z.array(EventSchema),
                  }),
                ])
              : ApplicationSchema;
  return z.object({ result });
}
export const IdInput = z.object({ applicationId: z.string().min(1) });
