import { z } from "zod";

export const Field = z.object({
  frameId: z.number().int().default(0),
  selector: z.string(),
  label: z.string(),
  type: z.string(),
  uploadRole:z.enum(['resume_import','resume','cover_letter']).optional(),
  required: z.boolean(),
  value: z.string().default(""),
  options: z.array(z.string()).default([]),
  files: z.array(z.string()).default([]),
  accept: z.string().default(""),
  invalid: z.boolean().default(false),
  maxLength: z.number().int().positive().optional(),
  focused:z.boolean().default(false),
  history: z.object({ section: z.enum(["experience", "education"]), index: z.number().int().min(0), key: z.string(), orderedBlankRow:z.boolean().optional() }).optional(),
});
export type Field = z.infer<typeof Field>;
export const Snapshot = z.object({
  educationSection: z.object({text:z.string(),hasRecords:z.boolean()}).optional(),
  url: z.string(),
  title: z.string(),
  fields: z.array(Field),
  buttons: z.array(
    z.object({
      frameId: z.number(),
      selector: z.string(),
      label: z.string(),
      href: z.string().optional(),
      educationIndex:z.number().int().min(0).optional(),
    }),
  ),
  blockers: z.array(z.string()),
  confirmation: z.string().default(""),
  diagnostics: z.object({
    closedShadowRoots: z.number().default(0),
    shadowRoots: z.number().default(0),
    iframes: z.array(z.string()).default([]),
    frames: z.array(z.string()).default([]),
    scannedFrames: z.number().default(0),
  }).partial().optional(),
  reviewText: z.string().default(""),
  supportsFocus:z.boolean().default(false),
  supportsByteUploads:z.boolean().default(false),
  attachments: z
    .array(
      z.object({
        kind: z.enum(["resume", "cover_letter"]),
        name: z.string(),
        frameId: z.number(),
        // Indeed review page: the file Indeed is set to send, which may be an
        // older upload rather than this job's document.
        shownByIndeed: z.boolean().optional(),
      }),
    )
    .default([]),
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
  // Studio run (generation) the documents came from; a newer run means regenerated.
  runId: z.string().optional(),
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
  formFormat: z.string().optional(),
  finalSubmitBy: z.enum(["user", "approved_agent"]).optional(),
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
      uploadAttemptedAt: z.string().optional(),
    }),
  ),
  filled: z.array(
    z.object({ label: z.string(), value: z.string(), source: z.string() }),
  ),
  answerDrafts: z.array(z.object({question:z.string(),answer:z.string(),evidence:z.array(z.string()),sourceHash:z.string(),createdAt:z.string()})).optional(),
  manualWatches:z.array(z.object({label:z.string(),selector:z.string(),frameId:z.number(),reuse:z.boolean(),baseline:z.string(),contextKey:z.string().optional(),candidate:z.string().optional(),seenAt:z.number().optional(),saved:z.boolean().default(false)})).optional(),
  reason: z.string(),
  preparationStage:z.enum(['preparing','uploading','needs_user']).optional(),
  educationBatchSourceHash:z.string().optional(),
  retryMissingDocumentsRequested:z.boolean().optional(),
  indeedResumeEditAt: z.string().optional(),
  indeedCoverAddAt: z.string().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
  reviewHash: z.string().optional(),
  approvedHash: z.string().optional(),
  approvedAt: z.string().optional(),
  confirmation: z.string().optional(),
  manualSubmissionReportedAt: z.string().optional(),
  manuallyConfirmedAt: z.string().optional(),
  verificationSource: z.enum(["employer_confirmation", "user_confirmation", "studio_record"]).optional(),
  synced: z.boolean().optional(),
  deferredAt: z.string().optional(),
  cancelledAt: z.string().optional(),
  linkHealth: z.enum(['available','session_expired','unavailable']).optional(),
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
