# HR outreach through n8n: setup and test walkthrough

The app never sends mail. It drafts, you approve, it hands approved messages to n8n,
and n8n sends through Gmail and reports back. This page is the end-to-end test you run
once after setup, and again after any change to the workflows.

## What runs where

| Piece | Where | Does |
|---|---|---|
| Review screen | Resume Studio, **Outreach** tab | Draft, edit, approve, dispatch, kill switch, suppression, audit log |
| `outreach-dispatch` workflow | n8n | Receives a batch, checks the shared secret, sends each message through Gmail, calls back `sent` or `failed`, logs to a sheet |
| `outreach-reply-watch` workflow | n8n | Polls the Gmail inbox, matches replies and bounces to open messages, calls back `replied` or `bounced` |
| `POST /api/outreach/callback` | Resume Studio | Applies the event, stops sequences on reply or bounce, writes the audit log |

## One-time setup

1. **Secret.** Generate one and put the same value in two places:

   ```
   python -c "import secrets; print(secrets.token_hex(24))"
   ```

   In the app's `.env`: `OUTREACH_SHARED_SECRET=<value>` and
   `OUTREACH_WEBHOOK_URL=http://host.docker.internal:5678/webhook/outreach-dispatch`.
   In n8n, add two environment variables to the n8n container (`docker-compose`
   `environment:` or the n8n `.env`): `OUTREACH_SHARED_SECRET=<value>` and
   `RESUME_STUDIO_URL=http://host.docker.internal:8088`. Restart both containers.

2. **Import the workflows.** In n8n: Workflows, Import from file,
   `n8n/workflows/outreach-dispatch.workflow.json`, then
   `n8n/workflows/outreach-reply-watch.workflow.json`.

3. **Credentials.** Open each Gmail node and pick your Gmail OAuth credential. Open the
   Google Sheets node and pick your Sheets credential, then paste the spreadsheet id of a
   sheet with a tab named `Outreach` and this header row:

   ```
   date,batch_id,message_id,company,to,subject,template,step,lane,pathway,status,gmail_id
   ```

4. **Activate** both workflows. The dispatch workflow's production URL must end in
   `/webhook/outreach-dispatch` (matches `OUTREACH_WEBHOOK_URL`).

## Test 1: the callback endpoint answers (no n8n needed)

From the app machine:

```
curl -s -X POST http://127.0.0.1:8088/api/outreach/callback \
  -H "Content-Type: application/json" -H "X-Outreach-Secret: WRONG" \
  -d '{"message_id":"x","event":"sent"}'
```

Expected: HTTP 401 `Bad or missing X-Outreach-Secret`. Repeat with the right secret and a
made-up message id. Expected: HTTP 404 `Unknown message_id`. Both attempts appear in the
Outreach tab's audit log as `callback_rejected` (the first) or nothing (the second, because
there was no message to attach it to). If you get a 401 with the right secret, the app
container did not pick up `.env`: recreate it.

## Test 2: a dry run through n8n (no email leaves)

1. Import a batch (Intake tab, **Import day batch**) that includes an `hr_companies` file,
   or add a contact by hand in the Outreach tab. Use your own address as the HR email
   so any real send lands with you.
2. In the Outreach tab, pick a Tier A or B job, the contact, the **Direct application
   follow-up** template, and **Draft**. Two rows appear, both `queued`: step 1 now and step
   2 in seven days. Read them. Edit if you want. The subject stays under 60 characters and
   the body under 150 words or the edit is refused.
3. Tick step 1 only and **Approve**. Step 2 stays `queued`. Nothing can ever send it
   until you approve it separately.
4. Click **Preview dispatch**. It lists what would go and every reason something would
   not (cooldown, cap, suppression, another live sequence at that company). Fix anything
   surprising before continuing.
5. Click **Dispatch (test)**. The app posts the batch with `test: true`. n8n's dispatch
   workflow takes the **Test mode** branch: no Gmail node runs, and n8n calls back `sent`
   with a `test-` provider id. Within a second the row shows `sent` and the audit log
   shows `dispatched` then `callback:sent`. If the row stays `sending`, n8n received the
   batch but the callback did not reach the app: check `RESUME_STUDIO_URL` inside n8n.
   If the row stays `approved` with an error, the webhook did not acknowledge: check the
   secret and that the workflow is active.

## Test 3: a real send to yourself

1. Draft and approve a message to a contact whose address is your own.
2. Click **Dispatch**. n8n sends through Gmail and calls back `sent` with the real Gmail
   id and thread id. The Outreach sheet gains a row.
3. Reply to that email from the receiving mailbox. Within ten minutes the reply-watch
   workflow matches the thread and calls back `replied`. The message shows `replied`,
   any pending step in that sequence flips to `cancelled`, and the dashboard's reply rate
   moves.
4. Draft and approve a message to a deliberately bad address at a real domain
   (`nobody-xyz123@gmail.com`). Dispatch. The bounce arrives from `mailer-daemon`; the
   watcher calls back `bounced`. The contact becomes `do_not_contact` with a bad-address
   flag and no further message can be drafted to it.

## Test 4: guardrails in the UI

- Flip the **kill switch** on and click Dispatch: nothing goes, the banner says why.
- Set the daily cap to 0 and dispatch: rows show `deferred: daily cap`, stay `approved`,
  and go the next day once the cap is back.
- Add your own address to the suppression list and dispatch: blocked with `suppressed`.
- Draft to a contact whose confidence is `pattern_guess`: only step 1 is created, and a
  second sequence to that address is blocked forever after the first send.

## When something fails

Every failure is on the row and in the audit log. A row that says `approved` with a
red error was refused by n8n or the network and will be retried on the next dispatch.
A row stuck at `sending` for more than a few minutes means n8n accepted it but never
called back: open the n8n execution list, find the batch id, and read the failing node.
Nothing is ever marked `sent` without n8n saying so.
