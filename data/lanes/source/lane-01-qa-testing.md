# Lane 1 | QA and software testing

NOC 22222, TEER 2. Priority lane, and lane 1 by Keerthi's direction. Read `00-index.md` for the Status conventions and tier rules.

**PR note.** 22222 lost its BC PNP route when BC removed the priority technology list on 23 April 2026. AIP from a designated Atlantic employer is now the one designated pathway for this code, and an Ontario job offer qualifies under the Workforce Priority stream. Weight Atlantic and Ontario QA roles accordingly.

## NOC map

| NOC | Title | TEER | When it applies |
|---|---|---|---|
| 22222 | Information systems testing technicians | 2 | Manual and automated software testing, test case design, defect management. The lane's home code. |
| 21232 | Software developers and programmers | 1 | SDET and test-automation-engineer seats where the body is mostly writing code. Stronger code, read the duties before claiming it. |
| 21222 | Information systems specialists | 1 | QA seats folded into a broader systems-analysis role. |

## Must

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| Test case design | Writing cases from requirements, positive and negative paths, boundary and equivalence | not yet | |
| Manual testing execution | Functional, regression, smoke, UAT support, cross-browser and cross-device | partial | Manual testing of his own builds across K2 client sites and personal projects. Not against a formal test plan or in a team QA process. |
| Defect management | Reproduction steps, severity and priority, lifecycle through to retest and closure | partial | Issue tracking in his own GitHub repos. Not in Jira or an enterprise defect workflow. |
| Bug reporting quality | A report a developer can act on without a follow-up conversation | partial | Same as above, self-directed rather than reviewed. |
| SDLC and Agile | Sprints, ceremonies, where QA sits in the cycle, definition of done | not yet | |
| Test management tooling | Jira, Azure DevOps, TestRail, Zephyr or similar | not yet | |
| API testing | Postman or equivalent, request and response validation, status codes, payload assertions | partial | Heavy API and JSON work across the n8n pipelines and K2_Press. Covers request and response handling, not a structured API test suite. |
| SQL for test data | Querying to set up and verify test state | not yet | See lane 5, same gap, same fix. |

## Important

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| Test automation | Selenium, Playwright, Cypress. Playwright and Cypress dominate new postings | not yet | |
| Programming for automation | JavaScript or TypeScript or Python well enough to write and maintain tests | held | React, Next.js, TypeScript and Node.js work across K2 builds; Python across the automation pipelines. The language is there, the testing framework is not. |
| Git and CI | Branching, pull requests, tests running in a pipeline | held | github.com/K-Keerthivasan, multiple maintained repos. |
| Mobile and responsive testing | Device matrices, viewport behaviour | partial | Responsive verification on client sites. Not on a device lab or emulator matrix. |

## Optional

| Skill | Note | Status |
|---|---|---|
| Performance testing | JMeter, k6. Rarely required at junior level | not yet |
| Accessibility testing | WCAG, axe. Increasingly asked for in public-sector postings | not yet |
| ISTQB Foundation | Not required, but it is the one certification that reliably moves a junior QA resume | not yet |

## Later

| Skill | Note | Status |
|---|---|---|
| CI/CD pipeline ownership | Jenkins, GitHub Actions as the test owner rather than a user | not yet |
| Contract and integration testing | Pact, service virtualisation | not yet |

## Not required

Security testing, penetration testing, and formal test strategy ownership. Those are senior seats and a posting that hard-requires them has failed the seniority gate anyway.

## Honest positioning

The truth today: he can read and write the code QA roles automate against, he handles APIs and JSON fluently, and he has tested his own work. What he has not done is QA inside a team, against a test plan, in a defect workflow, with a test management tool. That is the whole gap and it is a process gap, not an intelligence gap, which is worth saying plainly in a cover letter rather than hiding.

On current statuses most QA postings grade Tier B or Tier C. **The fastest move to Tier A is Playwright or Cypress plus one public repo with a real test suite, and ISTQB Foundation if a run shows it appearing as a hard requirement more than occasionally.** Lane 1 and lane 5 share the SQL gap, so closing SQL once moves both lanes.

## Interview watch

QA screens are practical. Expect to be handed a feature and asked what you would test, and expect a follow-up on how you would prioritise when there is not time to test everything. Have an answer for both. Also expect "what is the difference between severity and priority", which is the single most common QA screening question.

## Sourcing vocabulary

- **Core:** qa analyst, quality assurance analyst, software tester, qa tester, test analyst, junior qa, qa engineer, quality assurance specialist, test engineer, qa specialist.
- **Tool-anchored, high signal:** playwright tester, selenium tester, automation tester, sdet, test automation engineer.
- **Adjacent, worth opening:** uat analyst, quality analyst, release coordinator, application tester.

## Aliases

Alternate names the grader matches against posting text, one line per skill. The skill name before the colon must match a row in the tables above.

- Test case design: test cases, test plans, test planning, test scenarios, test design, test documentation
- Manual testing execution: manual testing, functional testing, regression testing, smoke testing, UAT, user acceptance testing, exploratory testing, cross-browser testing, end-to-end testing
- Defect management: defect tracking, bug tracking, defect lifecycle, bug triage, defect triage, defect reporting
- Bug reporting quality: bug reports, defect reports, reproduction steps, steps to reproduce
- SDLC and Agile: agile, scrum, sdlc, software development life cycle, sprints, kanban, agile methodology
- Test management tooling: jira, azure devops, testrail, zephyr, xray, qtest, ado, hp alm
- API testing: postman, rest api testing, api tests, soapui, swagger, api validation, rest assured
- SQL for test data: sql, sql queries, database queries, test data
- Test automation: selenium, playwright, cypress, automated testing, test automation framework, webdriver, appium, robot framework, automation scripts
- Programming for automation: javascript, typescript, python, java, c#
- Git and CI: git, github, gitlab, ci/cd, continuous integration, jenkins, github actions, bitbucket
- Mobile and responsive testing: mobile testing, responsive testing, ios testing, android testing, browserstack, device testing
- Performance testing: jmeter, k6, load testing, performance testing, loadrunner, gatling, stress testing
- Accessibility testing: wcag, accessibility testing, axe, aoda, accessibility
- ISTQB Foundation: istqb, ctfl, istqb certified
- CI/CD pipeline ownership: jenkins pipelines, azure pipelines, pipeline ownership
- Contract and integration testing: pact, contract testing, integration testing, service virtualization
