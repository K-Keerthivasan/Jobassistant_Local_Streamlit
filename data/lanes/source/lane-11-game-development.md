# Lane 11 | Game development and game design

New in v3.5. NOC 21232, TEER 1. Read `00-index.md` for the Status conventions and tier rules.

**The headline finding.** NOC 21232 Software developers and programmers is **TEER 1**, and its illustrative example titles include **"computer game developer"**, **"interactive media developer"** and **"multimedia developer"**. Game development is not a weaker code than software development. It is the same code. That means this lane carries the full PR value of lane 4: North Bay RCIP lists 21232, MPNP listed it as of v3.1 (re-verify), AIP covers it from a designated Atlantic employer, and Ontario's Workforce Priority stream takes it with a qualifying offer. This lane costs him nothing on the immigration side, which was the thing worth checking before building it.

## NOC map

| NOC | Title | TEER | When it applies |
|---|---|---|---|
| **21232** | Software developers and programmers | **1** | The home code. "Computer game developer" and "interactive media developer" are named examples. Any gameplay, engine, tools or systems programming seat. |
| 21231 | Software engineers and designers | 1 | Engine and architecture-level seats. Steinbach RCIP code. |
| 52120 | Graphic designers and illustrators | 2 | Only where the seat is genuinely art-led rather than technical. Weaker, and not where he should aim. |

**The mapping caution for this lane.** A **game programmer** maps cleanly to 21232 and is unambiguous. A **pure game designer** doing systems, level and encounter design with no code is genuinely ambiguous in NOC 2021 and gets argued either way. His Fanshawe program is Game Development: Advanced Programming, and his project evidence is code, so **the programmer framing is both the honest one and the stronger one on every axis: skills, evidence and NOC**. Read the body: if a "Game Designer" posting is documentation, systems tuning and level layout with no implementation, keep it but note the NOC ambiguity in the fit report gap flags rather than asserting 21232.

## Credentials

- **Game Development: Advanced Programming, Fanshawe College, London ON (2023 to 2024).** A named game development credential, which is what most junior game postings ask for and most junior applicants substitute a portfolio for. He has both.
- **Master of Computer Applications, Anna University (2020 to 2022).** Carries the post-secondary credential requirement for the Ontario Workforce Priority stream.

## Must

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| C++ | The language of the industry, especially engine and gameplay code | held | Custom game engine built from scratch in C++ and OpenGL. Haply Robotics C++ work bridging CHAI 3D. |
| C# | Unity's language | held | Haply Robotics: Unity scripts, native plugins, and C# to C++ interop for real-time bidirectional haptics. |
| A named engine | Unreal or Unity. Postings name one, rarely both | held | Both. Unity through Haply Robotics and coursework; Unreal Engine 5 through Death Bridge and the JKR channel work. |
| Gameplay programming | Mechanics, state, player systems | held | Death Bridge implementation plus the Fanshawe programme. |
| 3D maths | Vectors, matrices, transforms, collision | held | Custom engine: rendering pipeline, animation, physics basics, collision detection, all hand-built. |
| Version control | Git, and awareness that games teams often use Perforce | held | Maintained public repos. Perforce specifically is a gap, see Important. |
| Debugging and profiling | Finding the bug and finding the frame cost | partial | Real debugging across engine and interop work. Formal profiling against a frame budget is not evidenced. |
| Game design fundamentals | Loops, pacing, player feedback, why a mechanic works | partial | Death Bridge is his own design work, so the thinking is real. It has not been tested against players or a design review. |

## Important

| Skill | What the roles ask for | Status | Evidence |
|---|---|---|---|
| Shaders and graphics programming | HLSL, GLSL, material work | held | Custom shaders and a hand-built OpenGL rendering pipeline. Genuinely uncommon at junior level. |
| Perforce | The standard version control in games studios | not yet | Named often. Cheap to close and worth doing. |
| A shipped or playable build | Something someone else can actually play | partial | Death Bridge is in progress. **This is the single highest-leverage gap in the lane.** |
| Level design tooling | Building playable space in-engine | partial | Death Bridge environments. Not evidenced as a standalone discipline. |
| UI implementation | In-engine UI systems | partial | UI work across engine and app projects. |
| Physics and animation systems | Working with, not just against | held | Custom engine covers both; Haply work is multi-physics environments. |
| Agile in a studio | Sprints, milestones, producers | not yet | Same gap as every other lane: he has not worked inside a team process. |

## Optional

| Skill | Note | Status |
|---|---|---|
| Blender or Maya | Enough to handle and fix assets | partial |
| Multiplayer and networking | Narrows the market when absent, but rarely junior-required | not yet |
| Console certification | Platform-holder requirements | not yet |
| Game jams | The cheapest credible way to show finished work and teamwork | not yet |

## Later

| Skill | Note | Status |
|---|---|---|
| Engine architecture at team scale | Senior territory | not yet |
| Technical direction | Senior territory | not yet |

## Not required

Published shipped titles, AAA credits, or a games-specific degree beyond what he has. A posting hard-requiring shipped commercial titles has effectively failed the seniority gate.

## Sourcing vocabulary

- **Core:** junior game developer, game programmer, gameplay programmer, junior gameplay engineer, Unity developer, Unreal developer, Unreal Engine programmer, game engine programmer, tools programmer, junior game designer, level designer, technical designer.
- **Adjacent and worth opening:** interactive developer, simulation developer, real-time 3D developer, XR developer, AR/VR developer, technical artist. **Simulation and real-time 3D outside games is the underrated half of this lane** and it is where the Haply Robotics haptics work lands perfectly: training simulation, medical simulation, industrial digital twins and visualisation all hire exactly this skill set and compete for far fewer candidates than games studios do.
- **Geography reality:** the Canadian games market concentrates in Montreal, Toronto, Vancouver and Quebec City, with a real cluster in Kitchener-Waterloo that is commutable-adjacent from London. **Montreal and Quebec City postings frequently require French**, which is a language-gate drop, so expect Quebec yield to be low and do not read that as the lane being dry.

## Honest positioning

This lane is stronger than it looks on a resume summary. A junior applicant who has **built a game engine from scratch in C++ and OpenGL** with shaders, a rendering pipeline, animation, physics and collision is not a typical junior applicant, and neither is one who wrote C# to C++ interop for real-time haptics on a research project. Lead with the engine and the Haply work, in that order, because they demonstrate the thing studios actually screen for at junior level: can this person reason about systems and performance, or have they only followed tutorials.

The honest gap is the one every self-taught and recently-graduated game candidate has: **no finished, playable thing that someone else has played.** Death Bridge is in progress and a playable vertical slice would move this lane more than any additional skill. A game jam would do the same job faster and adds the team-working evidence he is missing everywhere.

Most postings in this lane grade Tier B on current statuses, moving to Tier A once there is a playable build. Perforce is the one cheap named gap.

## Interview watch

Expect a technical screen on C++ or C# fundamentals and 3D maths, and expect questions about the engine project specifically since it is the most interesting thing on the resume. Be ready to explain a design decision inside it and what you would do differently. Expect "what games do you play and what would you change about one" for design-leaning seats, which rewards a specific mechanical answer over enthusiasm. For simulation and real-time roles, lead with Haply rather than Death Bridge.

## Aliases

Alternate names the grader matches against posting text, one line per skill. The skill name before the colon must match a row in the tables above.

- C++: c++, cpp, modern c++, c++17, c++20
- C#: c#, csharp, .net, unity c#
- A named engine: unreal engine, unreal, ue4, ue5, unity, unity3d, game engine, godot, unreal engine 5
- Gameplay programming: gameplay programming, gameplay, game mechanics, player systems, gameplay systems, gameplay programmer, gameplay features
- 3D maths: 3d math, 3d maths, linear algebra, vectors, matrices, quaternions, mathematics, collision detection, math skills
- Version control: git, github, gitlab, version control, source control, plastic scm
- Debugging and profiling: debugging, profiling, optimization, optimisation, performance, frame rate, memory management, performance optimization
- Game design fundamentals: game design, game feel, systems design, player experience, design documentation, gdd, game design principles
- Shaders and graphics programming: shaders, hlsl, glsl, graphics programming, rendering, opengl, directx, vulkan, materials, rendering pipeline, graphics
- Perforce: perforce, p4, helix core, p4v
- A shipped or playable build: shipped title, shipped game, published game, playable demo, portfolio of games, released game, shipped titles
- Level design tooling: level design, level editor, world building, environment design, blueprints, level layout
- UI implementation: ui implementation, ui programming, umg, unity ui, hud, menus, game ui
- Physics and animation systems: physics, animation systems, animation, physics engine, ragdoll, character animation, state machines, animation blueprints
- Agile in a studio: agile, scrum, sprints, jira, milestones, production pipeline, agile development
- Blender or Maya: blender, maya, 3ds max, 3d modelling, 3d modeling, asset pipeline, 3d assets
- Multiplayer and networking: multiplayer, networking, netcode, online, replication, photon, mirror, network programming
- Console certification: console, playstation, xbox, nintendo switch, trc, console development
- Game jams: game jam, game jams, ludum dare, itch.io
- Engine architecture at team scale: engine architecture, engine programming, core tech, engine development
- Technical direction: technical director, technical direction, technical lead
