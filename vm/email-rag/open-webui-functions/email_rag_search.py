"""
title: Email RAG Search
author: uptonx-homelab
version: 0.1.0
description: Search and query the email-rag pipeline data. Provides tools to search emails, view findings, explore timeline events, and ask natural-language questions over the email corpus.
"""

import json
from typing import Any
import urllib.request

EMAIL_RAG_BASE = "http://localhost:8000"


class Tools:
    def __init__(self):
        pass

    def search_emails(
        self,
        query: str = "",
        limit: int = 20,
        corpus: str = "",
        priority_only: bool = False,
        flagged_only: bool = False,
        has_attachments: bool = None,
        bulk: bool = None,
        __user__: dict = {},
    ) -> str:
        """
        Search ingested emails. Returns sender, recipients, subject, date, corpus, thread info,
        read/flagged/replied status, Gmail labels, attachment info, bulk detection, and importance.

        :param query: Optional keyword to filter results by subject or sender (client-side filter).
        :param limit: Max number of emails to return (default 20, max 200).
        :param corpus: Filter by corpus: "sent", "subject", or leave empty for all.
        :param priority_only: If true, only return priority (subject-related) emails.
        :param flagged_only: If true, only return starred/flagged emails.
        :param has_attachments: If true, only return emails with attachments. If false, only without.
        :param bulk: If true, only return bulk/automated emails. If false, exclude them.
        :return: JSON list of matching emails with full metadata.
        """
        params = [f"limit={limit}"]
        if corpus:
            params.append(f"corpus={corpus}")
        if priority_only:
            params.append("priority_only=true")
        if flagged_only:
            params.append("flagged_only=true")
        if has_attachments is not None:
            params.append(f"has_attachments={'true' if has_attachments else 'false'}")
        if bulk is not None:
            params.append(f"bulk={'true' if bulk else 'false'}")
        url = f"{EMAIL_RAG_BASE}/api/emails?{'&'.join(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                emails = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch emails: {e}"})

        if query:
            q = query.lower()
            emails = [
                e for e in emails
                if q in (e.get("subject") or "").lower()
                or q in (e.get("from") or "").lower()
            ]

        if not emails:
            return json.dumps({"message": "No emails found matching your criteria."})

        return json.dumps(emails, indent=2)

    def get_findings(
        self,
        limit: int = 20,
        grounding: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Get analysis findings from the email corpus. Findings are high-level insights extracted by AI analysis, including patterns, contradictions, timeline gaps, and behavioral observations.

        :param limit: Max number of findings to return (default 20, max 100).
        :param grounding: Filter by evidence level: "grounded", "inferred", "speculative", or empty for all.
        :return: JSON list of findings with title, summary, type, confidence, and supporting email IDs.
        """
        params = [f"limit={limit}"]
        if grounding:
            params.append(f"grounding={grounding}")
        url = f"{EMAIL_RAG_BASE}/api/findings?{'&'.join(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                findings = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch findings: {e}"})

        if not findings:
            return json.dumps({"message": "No findings available yet."})

        return json.dumps(findings, indent=2)

    def get_timeline(
        self,
        limit: int = 30,
        __user__: dict = {},
    ) -> str:
        """
        Get timeline of events extracted from emails. Shows key events, dates, and participants in chronological order.

        :param limit: Max number of timeline events to return (default 30, max 200).
        :return: JSON list of timeline events with date, type, description, and participants.
        """
        url = f"{EMAIL_RAG_BASE}/api/timeline?limit={limit}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                events = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch timeline: {e}"})

        if not events:
            return json.dumps({"message": "No timeline events available."})

        return json.dumps(events, indent=2)

    def query_emails(
        self,
        question: str,
        __user__: dict = {},
    ) -> str:
        """
        Ask a natural-language question about the email corpus using RAG. This performs semantic search over email content and uses an AI model to synthesize an answer with citations.

        :param question: The question to ask about the emails (e.g., "What emails mention the property closing?").
        :return: An AI-generated answer with source references.
        """
        url = f"{EMAIL_RAG_BASE}/api/query"
        payload = json.dumps({"question": question, "model": "claude"}).encode()

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to query emails: {e}"})

        if "error" in result:
            return json.dumps(result)

        return json.dumps(result, indent=2)

    def get_email_stats(
        self,
        __user__: dict = {},
    ) -> str:
        """
        Get high-level statistics about the email corpus: total messages, processed count,
        findings, claims, flagged/bulk/attachment/unread counts, and system status.

        :return: JSON object with corpus statistics including metadata counts.
        """
        url = f"{EMAIL_RAG_BASE}/api/stats"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                stats = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch stats: {e}"})

        return json.dumps(stats, indent=2)

    def get_user_facts(
        self,
        category: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Get user-provided background knowledge facts. These are contextual facts about people,
        places, relationships, events, and other context that help the system understand emails.

        :param category: Filter by category: "person", "relationship", "place", "event", "context", or empty for all.
        :return: JSON list of user facts with id, category, subject, and content.
        """
        params = []
        if category:
            params.append(f"category={category}")
        url = f"{EMAIL_RAG_BASE}/api/facts"
        if params:
            url += f"?{'&'.join(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                facts = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch facts: {e}"})

        if not facts:
            return json.dumps({"message": "No user facts available."})

        return json.dumps(facts, indent=2)

    def get_suggested_questions(
        self,
        status: str = "pending",
        limit: int = 20,
        __user__: dict = {},
    ) -> str:
        """
        Get system-generated questions about unknowns in the email corpus. Questions are
        generated during analysis when the system encounters unknown people, places, or
        gaps in the timeline.

        :param status: Filter by status: "pending", "answered", "dismissed", or empty for all.
        :param limit: Max number of questions to return (default 20).
        :return: JSON list of suggested questions with id, text, context, source_type, and status.
        """
        params = [f"limit={limit}"]
        if status:
            params.append(f"status={status}")
        url = f"{EMAIL_RAG_BASE}/api/questions?{'&'.join(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                questions = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to fetch questions: {e}"})

        if not questions:
            return json.dumps({"message": "No questions found."})

        return json.dumps(questions, indent=2)

    def answer_question(
        self,
        question_id: int,
        answer: str,
        save_as_fact: bool = False,
        category: str = "context",
        subject: str = "",
        __user__: dict = {},
    ) -> str:
        """
        Answer a suggested question. Optionally save the answer as a user fact for
        future reference in analysis and RAG queries.

        :param question_id: The ID of the question to answer.
        :param answer: The answer text.
        :param save_as_fact: If true, also save the answer as a user fact.
        :param category: Fact category if saving as fact: "person", "relationship", "place", "event", "context".
        :param subject: Short label for the fact if saving as fact.
        :return: JSON result with question status and optional fact ID.
        """
        url = f"{EMAIL_RAG_BASE}/api/questions/{question_id}/answer"
        payload = {"answer": answer}
        if save_as_fact:
            payload["save_as_fact"] = True
            payload["category"] = category
            payload["subject"] = subject

        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
        except Exception as e:
            return json.dumps({"error": f"Failed to answer question: {e}"})

        return json.dumps(result, indent=2)
