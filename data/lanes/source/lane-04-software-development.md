# Lane 4 | Software development

NOC 21232, 21231, 21233, TEER 1 to 2. Secondary lane. Read `00-index.md` for the Status conventions and tier rules.

**PR note.** 21232 is on the North Bay RCIP list and was on MPNP as of v3.1 (re-verify). 21231 is on the Steinbach RCIP list. AIP covers the lane, and Ontario's Workforce Priority stream takes any of these with a qualifying offer. Strong codes, all TEER 1.

## NOC map

| NOC | Title | TEER | When it applies |
|---|---|---|---|
| 21232 | Software developers and programmers | 1 | The default. Full stack, backend, frontend, web. |
| 21231 | Software engineers and designers | 1 | Where the posting carries architecture or design responsibility. Steinbach RCIP code. |
| 21233 | Web designers | 1 | Design-leaning web seats. |

## Must

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| JavaScript and TypeScript | The working languages of most postings in this lane | held | K2 client builds, K2_Press, the local generation app. |
| React | Named in the large majority of frontend and full stack postings | held | K2 Digital Media client work. |
| Next.js | Increasingly the default React framework in postings | held | K2 Digital Media client work. |
| Node.js | Backend of the same stack | held | K2_Press and the local pipeline app. |
| HTML and CSS | Responsive layout, modern CSS | held | K2 Digital Media, web development is a core agency service. |
| REST APIs | Designing and consuming | held | Every project he runs is API-integrated. |
| Git workflow | Branching, pull requests, code review participation | held | Four maintained public repos. |
| Databases | Reading and writing from an application, schema basics | partial | Firebase and Supabase in production. Relational SQL depth is the gap, same one as lane 5. |

## Important

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| SQL and relational databases | PostgreSQL and MySQL, joins and schema design | not yet | Supabase is Postgres underneath, so this gap is smaller than it looks and worth closing deliberately. |
| Testing | Jest, Vitest, React Testing Library | not yet | Shared gap with lane 1. Closing it serves both lanes. |
| Python | Second language on many backend postings | held | Automation and pipeline work. |
| C# or C++ | Enterprise and systems postings | partial | Coursework and project-level work. Not production. |
| Cloud deployment | Vercel, Netlify, AWS, Azure | partial | Firebase, Supabase and Vercel-class deployment. Not major-cloud platform work. |
| CI/CD | Automated build and deploy | partial | Repo-level automation, not team pipeline ownership. |

## Optional

| Skill | Note | Status |
|---|---|---|
| Java | Foundational for him. Never a hard blocker on enterprise dev roles per the standing rule | partial |
| Docker and Kubernetes | Kubernetes familiarity is foundational and never a hard blocker | partial |
| GraphQL | A minority of postings | not yet |

## Later

| Skill | Note | Status |
|---|---|---|
| System design at scale | Senior territory | not yet |
| Microservices architecture | Senior territory | not yet |

## Not required

Anything requiring a computer science degree as a hard prerequisite, which is a credential-gate drop rather than a skill gap.

## Honest positioning

He builds and ships real web software for paying clients, which is more than most junior applicants can say, and the modern React and Next.js stack he works in is exactly what postings ask for. The honest shape of the gap is that agency work is broad and shallow where product work is narrow and deep: he has built many things once rather than one thing for two years, and he has not worked inside a team codebase with code review, tests and a release process.

Say that plainly rather than letting an interviewer discover it. Most postings in this lane grade Tier A or Tier B, and the two recurring gaps are **automated testing** and **relational SQL**, both shared with other lanes, which makes them the highest-leverage things to close anywhere in this search.

## Interview watch

Expect a code exercise and expect a conversation about a project you chose. Pick K2_Press or the automation pipeline rather than a tutorial project, and be ready to say what you would do differently now. Expect a question about working with other people's code, which is the real gap, so answer it honestly with how you handle unfamiliar repos rather than claiming team experience you do not have.

## Sourcing vocabulary

- **Core:** software developer, full stack developer, web developer, frontend developer, backend developer, junior developer, application developer, software engineer, junior software developer.
- **Tool-anchored, high signal:** react developer, next.js developer, node.js developer, typescript developer, javascript developer, python developer, wordpress developer.
- **Adjacent, worth opening:** web application developer, api developer, junior programmer, developer analyst.

## Aliases

Alternate names the grader matches against posting text, one line per skill. The skill name before the colon must match a row in the tables above.

- JavaScript and TypeScript: javascript, typescript, js, ts, es6, ecmascript
- React: react, react.js, reactjs, redux, react hooks
- Next.js: next.js, nextjs, next
- Node.js: node.js, nodejs, node, express, express.js, nestjs
- HTML and CSS: html, css, html5, css3, sass, scss, tailwind, tailwind css, bootstrap, responsive design
- REST APIs: rest, rest api, rest apis, restful, apis, api development, http, api design
- Git workflow: git, github, gitlab, bitbucket, pull requests, code review, version control
- Databases: firebase, supabase, mongodb, nosql, database, databases, firestore, dynamodb
- SQL and relational databases: sql, postgresql, postgres, mysql, sql server, relational database, relational databases, rdbms, t-sql, mariadb
- Testing: jest, vitest, react testing library, unit testing, unit tests, mocha, tdd, automated tests, test coverage, testing frameworks
- Python: python, django, flask, fastapi
- C# or C++: c#, .net, c++, dotnet, asp.net, .net core, csharp, cpp
- Cloud deployment: vercel, netlify, aws, azure, gcp, cloud, heroku, deployment, cloud platforms
- CI/CD: ci/cd, continuous integration, continuous deployment, github actions, jenkins, pipelines, build pipelines
- Java: java, spring, spring boot, jvm
- Docker and Kubernetes: docker, kubernetes, k8s, containers, containerization
- GraphQL: graphql, apollo
- System design at scale: system design, distributed systems, scalability, high availability, large-scale systems
- Microservices architecture: microservices, event-driven, kafka, service-oriented, message queues
