"""Phase 5, 6, 7 — AI Analysis, Resume Summary, Interview Questions.

Wraps OpenAI's chat completions API behind a small adapter so the provider can be
swapped later (e.g. for Gemini) without touching route code. Prompts request
strict JSON output, which is validated before it's returned/stored.
"""

import json

from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _build_profile_context(developer: dict, repos: list[dict], languages: dict, activity: dict) -> str:
    top_repos = sorted(repos, key=lambda r: r["stars"], reverse=True)[:8]
    return json.dumps(
        {
            "username": developer["github_username"],
            "followers": developer["followers"],
            "public_repos": developer["public_repos"],
            "top_repositories": [
                {
                    "name": r["name"],
                    "stars": r["stars"],
                    "language": r["primary_language"],
                    "topics": r.get("topics", []),
                }
                for r in top_repos
            ],
            "language_distribution_percent": languages.get("distribution_percent", {}),
            "commits_per_month": activity.get("commits_per_month", {}),
            "longest_streak_weeks": activity.get("longest_streak_weeks", 0),
        },
        default=str,
    )


async def generate_skill_analysis(developer: dict, repos: list[dict], languages: dict, activity: dict) -> dict:
    context = _build_profile_context(developer, repos, languages, activity)
    system_prompt = (
        "You are a senior technical recruiter analyzing a developer's GitHub profile. "
        "Respond ONLY with a JSON object with exactly these keys: "
        '"strengths" (array of short strings), "weaknesses" (array of short strings), '
        '"likely_expertise" (array of short strings), "suggested_learning" (array of short strings). '
        "Base every claim strictly on the data given. No commentary outside the JSON."
    )
    client = get_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Developer profile data:\n{context}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(response.choices[0].message.content)


async def generate_resume_summary(developer: dict, skill_analysis: dict) -> str:
    system_prompt = (
        "You write concise, professional 2-3 sentence resume/LinkedIn summaries for software "
        "developers based on their GitHub analysis. Respond with plain text only, no markdown, "
        "no quotes around the summary."
    )
    user_prompt = (
        f"Username: {developer['github_username']}\n"
        f"Strengths: {skill_analysis.get('strengths')}\n"
        f"Likely expertise: {skill_analysis.get('likely_expertise')}\n"
    )
    client = get_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
    )
    return response.choices[0].message.content.strip()


async def generate_interview_questions(developer: dict, languages: dict, skill_analysis: dict) -> list[str]:
    primary_language = languages.get("primary_language", "their primary language")
    system_prompt = (
        "You generate personalized technical interview questions for a developer based on their "
        "GitHub profile. Respond ONLY with a JSON object: {\"questions\": [array of 5 short, "
        "specific technical questions]}."
    )
    user_prompt = (
        f"Primary language: {primary_language}\n"
        f"Likely expertise: {skill_analysis.get('likely_expertise')}\n"
        f"Weaknesses to probe: {skill_analysis.get('weaknesses')}\n"
    )
    client = get_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.6,
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("questions", [])
