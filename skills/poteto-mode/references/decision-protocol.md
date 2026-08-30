# Structured Decision Protocol

Apply when human input is strictly necessary. Never use open-ended, conversational questions for technical forks.

## Non-Negotiable Rules

1. **Prototype first.** If the question can be settled by running a probe or benchmark, do not ask the human. Run the experiment and report the result.
2. **One recommended default.** Always declare the recommended option up front.
3. **Numbered single-letter choices.** Allow the user to respond with a single number or letter.
4. **Concrete consequences.** Every option must state what changes and what risks it introduces.

## Format Template

```text
### Decision Required: <Topic>

**Context.** <1-2 concise declarative sentences explaining the fork.>

**Recommendation.** Option 1. <Reason in one sentence.>

**Options:**
- **[1] <Option Name> (Recommended).** <Description>. Impact: <Consequences>.
- **[2] <Option Name>.** <Description>. Impact: <Consequences>.
- **[3] Abort / Custom.** <Description>.

Reply with `1`, `2`, or your custom direction.
```
