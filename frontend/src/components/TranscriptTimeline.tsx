"use client";

import { useState } from "react";

interface TranscriptTurn {
  speaker: string;
  text: string;
  timestamp?: string;
  timestamp_ms?: number;
  type?: string;
}

interface TranscriptTimelineProps {
  transcript: TranscriptTurn[];
}

interface QAGroup {
  entries: TranscriptTurn[];
}

function formatTimestamp(isoString: string, baseTime: number): string {
  const offset = new Date(isoString).getTime() - baseTime;
  if (offset < 0) return "00:00";
  const mins = Math.floor(offset / 60000);
  const secs = Math.floor((offset % 60000) / 1000);
  return String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0");
}

export default function TranscriptTimeline({ transcript }: TranscriptTimelineProps) {
  const [copied, setCopied] = useState(false);
  const [showSystemMessages, setShowSystemMessages] = useState(false);

  // Determine if transcript has type data (new format)
  const hasTypeData = transcript.some((t) => t.type);

  // Determine if transcript has timestamp data
  const hasTimestamps = transcript.some((t) => t.timestamp);

  // Find base time from earliest timestamp
  const baseTime = (() => {
    if (!hasTimestamps) return 0;
    let earliest: number | null = null;
    for (const t of transcript) {
      if (t.timestamp) {
        const ms = new Date(t.timestamp).getTime();
        if (earliest === null || ms < earliest) earliest = ms;
      }
    }
    return earliest ?? 0;
  })();

  // Filter silence prompts unless toggled on
  const filteredTranscript = hasTypeData
    ? transcript.filter((t) => showSystemMessages || t.type !== "silence_prompt")
    : transcript;

  // Group entries into Q&A sections (only if type data exists)
  const groups: QAGroup[] = (() => {
    if (!hasTypeData) {
      return [{ entries: filteredTranscript }];
    }
    const result: QAGroup[] = [];
    let currentGroup: TranscriptTurn[] = [];
    for (const entry of filteredTranscript) {
      if (entry.type === "question" && currentGroup.length > 0) {
        result.push({ entries: currentGroup });
        currentGroup = [];
      }
      currentGroup.push(entry);
    }
    if (currentGroup.length > 0) {
      result.push({ entries: currentGroup });
    }
    return result;
  })();

  const copyTranscript = () => {
    const filtered = transcript.filter((t) => t.type !== "silence_prompt");
    const text = filtered
      .map((t) => {
        const label = t.speaker === "bot" ? "Interviewer" : "Candidate";
        let timeStr = "";
        if (t.timestamp && baseTime) {
          timeStr = "[" + formatTimestamp(t.timestamp, baseTime) + "] ";
        }
        return timeStr + label + ": " + t.text;
      })
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(transcript, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "interview-transcript.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadText = () => {
    const filtered = transcript.filter((t) => t.type !== "silence_prompt");
    const base = filtered.find((t) => t.timestamp)?.timestamp;
    const baseMs = base ? new Date(base).getTime() : 0;

    let output = "Interview Transcript\n";
    output += "====================\n\n";
    if (base) {
      output += "Date: " + new Date(base).toLocaleDateString() + "\n";
    }
    output += "\n---\n\n";

    for (const t of filtered) {
      const label = t.speaker === "bot" ? "Interviewer" : "Candidate";
      let timeStr = "";
      if (t.timestamp && baseMs) {
        const offset = new Date(t.timestamp).getTime() - baseMs;
        const mins = Math.floor(offset / 60000);
        const secs = Math.floor((offset % 60000) / 1000);
        timeStr = "[" + String(mins).padStart(2, "0") + ":" + String(secs).padStart(2, "0") + "] ";
      }
      output += timeStr + label + ": " + t.text + "\n\n";
    }

    const blob = new Blob([output], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const dateStr = base ? new Date(base).toISOString().slice(0, 10) : "undated";
    a.download = "interview-transcript-" + dateStr + ".txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (transcript.length === 0) return null;

  const renderEntry = (turn: TranscriptTurn, i: number) => {
    const isBot = turn.speaker === "bot";
    const isSilencePrompt = turn.type === "silence_prompt";
    const isQuestion = turn.type === "question";
    const isFollowUp = turn.type === "follow_up";

    return (
      <div
        key={i}
        className={`flex gap-3 ${isBot ? "" : "flex-row-reverse"} ${isFollowUp ? "ml-3" : ""}`}
      >
        <div
          className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
            isBot
              ? "bg-blue-100 text-blue-700"
              : "bg-green-100 text-green-700"
          }`}
        >
          {isBot ? "AI" : "You"}
        </div>
        <div className="max-w-[75%]">
          {hasTimestamps && turn.timestamp && (
            <span className="text-xs text-slate-400 block mb-0.5">
              {formatTimestamp(turn.timestamp, baseTime)}
            </span>
          )}
          <div
            className={`rounded-lg px-3 py-2 text-sm ${
              isSilencePrompt
                ? "bg-slate-50 text-slate-400 italic text-xs"
                : isBot
                ? "bg-slate-50 text-slate-700"
                : "bg-blue-50 text-slate-700"
            } ${isQuestion ? "font-semibold border-l-2 border-violet-300 pl-2" : ""}`}
          >
            {turn.text}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-slate-900">Transcript</h3>
        <div className="flex gap-2 items-center">
          {hasTypeData && (
            <button
              onClick={() => setShowSystemMessages(!showSystemMessages)}
              className={`text-xs px-3 py-1.5 rounded-md border ${
                showSystemMessages
                  ? "border-slate-300 bg-slate-100 text-slate-700"
                  : "border-slate-200 text-slate-500 hover:bg-slate-50"
              }`}
            >
              {showSystemMessages ? "Hide system messages" : "Show system messages"}
            </button>
          )}
          <button
            onClick={copyTranscript}
            className="text-xs px-3 py-1.5 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
          <button
            onClick={downloadText}
            className="text-xs px-3 py-1.5 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            Download Text
          </button>
          <button
            onClick={downloadJson}
            className="text-xs px-3 py-1.5 rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            Download JSON
          </button>
        </div>
      </div>
      <div className="max-h-96 overflow-y-auto pr-2">
        {hasTypeData && groups.length > 1 ? (
          <div className="space-y-4">
            {groups.map((group, gi) => (
              <div key={gi} className={`space-y-2 ${gi > 0 ? "border-t border-slate-100 pt-4" : ""}`}>
                {group.entries.map((turn, ti) => renderEntry(turn, gi * 1000 + ti))}
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {filteredTranscript.map((turn, i) => renderEntry(turn, i))}
          </div>
        )}
      </div>
    </div>
  );
}
