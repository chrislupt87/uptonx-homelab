import React, { useState, useEffect, useCallback, useRef } from "react"

const apiUrl = window.location.origin

const STAGES = ["upload", "analyze", "process", "transcribe"]
const STAGE_LABELS = { upload: "Upload", analyze: "Analyze", process: "Process", transcribe: "Transcribe" }

const defaultParams = {
  denoise_mode: "spectral",
  noise_reduction: 30,
  noise_profile_seconds: 1.5,
  eq: { sub: 0, low: 0, lmid: 0, mid: 0, hmid: 0, high: 0 },
  comp: { threshold: -24, ratio: 4, attack: 3, release: 250, knee: 30 },
  gate: { enabled: true, threshold: -55 },
  voice_enhance: 0,
  harmonic_enhance: 0,
  gain_db: 0,
  lufs_target: -16,
}

function StageBar({ current, completed }) {
  return (
    <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
      {STAGES.map((s) => {
        const done = completed.includes(s)
        const active = s === current
        return (
          <div key={s} style={{
            flex: 1, padding: "8px 0", textAlign: "center", borderRadius: 6,
            background: done ? "#22c55e" : active ? "#3b82f6" : "#1e293b",
            color: done || active ? "#fff" : "#64748b",
            fontWeight: active ? 700 : 500, fontSize: 13, transition: "all 0.3s"
          }}>
            {done ? "\u2713 " : ""}{STAGE_LABELS[s]}
          </div>
        )
      })}
    </div>
  )
}

function MetricCard({ label, value, unit }) {
  return (
    <div style={{ background: "#1e293b", borderRadius: 8, padding: "12px 16px", minWidth: 120 }}>
      <div style={{ color: "#94a3b8", fontSize: 11, marginBottom: 4 }}>{label}</div>
      <div style={{ color: "#f1f5f9", fontSize: 18, fontWeight: 700 }}>
        {value != null ? value : "N/A"}{unit && <span style={{ fontSize: 12, color: "#64748b" }}> {unit}</span>}
      </div>
    </div>
  )
}

function EQSlider({ label, value, onChange }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <input type="range" min={-12} max={12} step={0.5} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ writingMode: "vertical-lr", direction: "rtl", height: 100 }} />
      <span style={{ fontSize: 11, color: "#94a3b8" }}>{value > 0 ? "+" : ""}{value}</span>
      <span style={{ fontSize: 10, color: "#64748b" }}>{label}</span>
    </div>
  )
}

function ProgressBar({ progress, label }) {
  return (
    <div style={{ marginBottom: 8 }}>
      {label && <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 4 }}>{label}</div>}
      <div style={{ background: "#1e293b", borderRadius: 6, height: 20, overflow: "hidden", position: "relative" }}>
        <div style={{
          background: "linear-gradient(90deg, #3b82f6, #22c55e)", height: "100%", borderRadius: 6,
          width: `${progress}%`, transition: "width 0.3s ease"
        }} />
        <span style={{
          position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, fontWeight: 600, color: "#fff"
        }}>{Math.round(progress)}%</span>
      </div>
    </div>
  )
}

function uploadWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", url)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        reject(new Error(`Request failed: ${xhr.status}`))
      }
    }
    xhr.onerror = () => reject(new Error("Network error"))
    xhr.send(formData)
  })
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [file, setFile] = useState(null)
  const [stage, setStage] = useState(null)
  const [completed, setCompleted] = useState([])
  const [analysis, setAnalysis] = useState(null)
  const [processResult, setProcessResult] = useState(null)
  const [transcript, setTranscript] = useState(null)
  const [params, setParams] = useState(defaultParams)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState("analysis")
  const [uploadProgress, setUploadProgress] = useState(0)
  const [statusText, setStatusText] = useState("")
  const dropRef = useRef(null)

  useEffect(() => {
    fetch(`${apiUrl}/api/health`).then(r => r.json()).then(setHealth).catch(() => setHealth({ status: "error" }))
  }, [])

  const handleFile = useCallback(async (f) => {
    setFile(f)
    setAnalysis(null)
    setProcessResult(null)
    setTranscript(null)
    setCompleted(["upload"])
    setStage("analyze")
    setError(null)
    setLoading(true)
    setUploadProgress(0)
    setStatusText("Uploading file...")
    setTab("analysis")

    try {
      const fd = new FormData()
      fd.append("file", f)
      const data = await uploadWithProgress(`${apiUrl}/api/analyze`, fd, (p) => {
        setUploadProgress(p)
        setStatusText(p < 100 ? "Uploading file..." : "Analyzing audio...")
      })
      setAnalysis(data)
      setCompleted(["upload", "analyze"])
      setStage("process")
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setUploadProgress(0)
      setStatusText("")
    }
  }, [])

  const handleProcess = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    setStage("process")
    setUploadProgress(0)
    setStatusText("Uploading file...")
    try {
      const fd = new FormData()
      fd.append("file", file)
      fd.append("params", JSON.stringify(params))
      const data = await uploadWithProgress(`${apiUrl}/api/process`, fd, (p) => {
        setUploadProgress(p)
        setStatusText(p < 100 ? "Uploading file..." : "Processing audio...")
      })
      setProcessResult(data)
      setCompleted(prev => [...new Set([...prev, "process"])])
      setStage("transcribe")
      setTab("processed")
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setUploadProgress(0)
      setStatusText("")
    }
  }

  const handleTranscribe = async () => {
    setLoading(true)
    setError(null)
    setStage("transcribe")
    setUploadProgress(0)
    setStatusText("Uploading file...")
    try {
      let fd = new FormData()
      if (processResult?.processed_wav_b64) {
        const bytes = Uint8Array.from(atob(processResult.processed_wav_b64), c => c.charCodeAt(0))
        const blob = new Blob([bytes], { type: "audio/wav" })
        fd.append("file", blob, "processed.wav")
      } else {
        fd.append("file", file)
      }
      const data = await uploadWithProgress(`${apiUrl}/api/transcribe`, fd, (p) => {
        setUploadProgress(p)
        setStatusText(p < 100 ? "Uploading file..." : "Transcribing audio...")
      })
      setTranscript(data)
      setCompleted(prev => [...new Set([...prev, "transcribe"])])
      setTab("transcript")
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      setUploadProgress(0)
      setStatusText("")
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const downloadReport = () => {
    const report = { analysis, processResult: processResult ? { job_id: processResult.job_id, analysis: processResult.analysis } : null, transcript, params, timestamp: new Date().toISOString() }
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `forensic-report-${analysis?.job_id || "unknown"}.json`
    a.click()
  }

  const downloadProcessedAudio = () => {
    if (!processResult?.processed_wav_b64) return
    const bytes = Uint8Array.from(atob(processResult.processed_wav_b64), c => c.charCodeAt(0))
    const blob = new Blob([bytes], { type: "audio/wav" })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `processed-${processResult.job_id}.wav`
    a.click()
  }

  const updateEQ = (band, val) => setParams(p => ({ ...p, eq: { ...p.eq, [band]: val } }))

  const btnStyle = (disabled) => ({
    padding: "10px 20px", borderRadius: 8, border: "none", cursor: disabled ? "not-allowed" : "pointer",
    background: disabled ? "#334155" : "#3b82f6", color: disabled ? "#64748b" : "#fff",
    fontWeight: 600, fontSize: 14, opacity: disabled ? 0.5 : 1
  })

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", color: "#e2e8f0", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, color: "#f1f5f9" }}>UptonX Forensic Audio Pipeline</h1>
            <span style={{ fontSize: 12, color: "#64748b" }}>v2.0 | {health?.status === "ok" ? "Connected" : "Connecting..."}</span>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {health?.whisper_loaded && <span style={{ background: "#166534", color: "#86efac", padding: "4px 10px", borderRadius: 12, fontSize: 11 }}>Whisper {health.whisper_model}</span>}
            {health?.deepfilter_enabled && <span style={{ background: "#1e3a5f", color: "#93c5fd", padding: "4px 10px", borderRadius: 12, fontSize: 11 }}>DeepFilter</span>}
          </div>
        </div>

        <StageBar current={stage} completed={completed} />

        {error && <div style={{ background: "#7f1d1d", color: "#fca5a5", padding: 12, borderRadius: 8, marginBottom: 16 }}>{error}</div>}

        {!file && (
          <div ref={dropRef} onDrop={handleDrop} onDragOver={(e) => e.preventDefault()}
            onClick={() => { const i = document.createElement("input"); i.type = "file"; i.accept = "audio/*"; i.onchange = (e) => e.target.files[0] && handleFile(e.target.files[0]); i.click() }}
            style={{ border: "2px dashed #334155", borderRadius: 12, padding: 60, textAlign: "center", cursor: "pointer", marginBottom: 24 }}>
            <div style={{ fontSize: 48, marginBottom: 8 }}>&#x1F399;</div>
            <div style={{ fontSize: 16, color: "#94a3b8" }}>Drop audio file here or click to browse</div>
            <div style={{ fontSize: 12, color: "#475569", marginTop: 8 }}>WAV, MP3, FLAC, M4A, OGG — no size limit</div>
          </div>
        )}

        {file && (
          <div style={{ background: "#1e293b", borderRadius: 8, padding: 12, marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{file.name} ({(file.size / 1024 / 1024).toFixed(1)} MB)</span>
            <button onClick={() => { setFile(null); setAnalysis(null); setProcessResult(null); setTranscript(null); setCompleted([]); setStage(null) }}
              style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer" }}>Clear</button>
          </div>
        )}

        {loading && (
          <div style={{ padding: "24px 0" }}>
            <ProgressBar progress={uploadProgress} label={statusText} />
            {uploadProgress >= 100 && (
              <div style={{ textAlign: "center", color: "#64748b", fontSize: 13, marginTop: 8 }}>
                Server is processing — this may take a while for large files
              </div>
            )}
          </div>
        )}

        {analysis && !loading && (
          <>
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              {["analysis", "params", "processed", "transcript", "custody"].map(t => (
                <button key={t} onClick={() => setTab(t)}
                  style={{ padding: "8px 16px", borderRadius: 6, border: "none", cursor: "pointer",
                    background: tab === t ? "#3b82f6" : "#1e293b", color: tab === t ? "#fff" : "#94a3b8", fontSize: 13, fontWeight: 600 }}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>

            {tab === "analysis" && (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8, marginBottom: 16 }}>
                  <MetricCard label="Duration" value={analysis.duration?.toFixed(1)} unit="s" />
                  <MetricCard label="RMS Level" value={analysis.rms_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Peak Level" value={analysis.peak_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Dynamic Range" value={analysis.dynamic_range_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="SNR Estimate" value={analysis.snr_estimate_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Speech Likelihood" value={(analysis.speech_likelihood_heuristic * 100)?.toFixed(0)} unit="%" />
                  <MetricCard label="Transcribability" value={(analysis.transcribability_heuristic * 100)?.toFixed(0)} unit="%" />
                  <MetricCard label="Noise Floor" value={analysis.noise_floor_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Spectral Centroid" value={analysis.spectral_centroid_hz?.toFixed(0)} unit="Hz" />
                  <MetricCard label="Pitch" value={analysis.pitch_fundamental_hz?.toFixed(0)} unit="Hz" />
                  <MetricCard label="Clipping" value={analysis.clipping_detected ? "Yes" : "No"} />
                  <MetricCard label="Silence Ratio" value={(analysis.silence_ratio * 100)?.toFixed(0)} unit="%" />
                </div>
                {analysis.spectrogram_url && (
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ fontSize: 14, color: "#94a3b8", marginBottom: 8 }}>Original Spectrogram</h3>
                    <img src={`${apiUrl}${analysis.spectrogram_url}`} alt="Spectrogram" style={{ width: "100%", borderRadius: 8 }} />
                  </div>
                )}
              </div>
            )}

            {tab === "params" && (
              <div style={{ background: "#1e293b", borderRadius: 8, padding: 20 }}>
                <h3 style={{ fontSize: 16, marginBottom: 16 }}>Processing Parameters</h3>

                <div style={{ marginBottom: 20 }}>
                  <h4 style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>Noise Reduction</h4>
                  <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
                    <label style={{ fontSize: 12 }}>Mode:
                      <select value={params.denoise_mode} onChange={e => setParams(p => ({ ...p, denoise_mode: e.target.value }))}
                        style={{ marginLeft: 8, background: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 4, padding: 4 }}>
                        <option value="spectral">Spectral</option>
                        <option value="neural">Neural (DeepFilter)</option>
                        <option value="both">Both</option>
                      </select>
                    </label>
                    <label style={{ fontSize: 12 }}>Amount: {params.noise_reduction}%
                      <input type="range" min={0} max={100} value={params.noise_reduction}
                        onChange={e => setParams(p => ({ ...p, noise_reduction: parseInt(e.target.value) }))} />
                    </label>
                  </div>
                </div>

                <div style={{ marginBottom: 20 }}>
                  <h4 style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>Parametric EQ (6-band)</h4>
                  <div style={{ display: "flex", gap: 16, justifyContent: "center" }}>
                    {[["sub", "60Hz"], ["low", "200Hz"], ["lmid", "500Hz"], ["mid", "2kHz"], ["hmid", "5kHz"], ["high", "12kHz"]].map(([k, l]) => (
                      <EQSlider key={k} label={l} value={params.eq[k]} onChange={v => updateEQ(k, v)} />
                    ))}
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 16, marginBottom: 20 }}>
                  <label style={{ fontSize: 12 }}>Voice Enhance: {params.voice_enhance}%
                    <input type="range" min={0} max={100} value={params.voice_enhance}
                      onChange={e => setParams(p => ({ ...p, voice_enhance: parseInt(e.target.value) }))} style={{ width: "100%" }} />
                  </label>
                  <label style={{ fontSize: 12 }}>Harmonic Exciter: {params.harmonic_enhance}%
                    <input type="range" min={0} max={100} value={params.harmonic_enhance}
                      onChange={e => setParams(p => ({ ...p, harmonic_enhance: parseInt(e.target.value) }))} style={{ width: "100%" }} />
                  </label>
                  <label style={{ fontSize: 12 }}>Output Gain: {params.gain_db} dB
                    <input type="range" min={-12} max={12} step={0.5} value={params.gain_db}
                      onChange={e => setParams(p => ({ ...p, gain_db: parseFloat(e.target.value) }))} style={{ width: "100%" }} />
                  </label>
                  <label style={{ fontSize: 12 }}>LUFS Target: {params.lufs_target}
                    <input type="range" min={-24} max={-6} step={1} value={params.lufs_target}
                      onChange={e => setParams(p => ({ ...p, lufs_target: parseInt(e.target.value) }))} style={{ width: "100%" }} />
                  </label>
                </div>

                <div style={{ marginBottom: 20 }}>
                  <h4 style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>Compressor</h4>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
                    <label style={{ fontSize: 12 }}>Threshold: {params.comp.threshold} dB
                      <input type="range" min={-60} max={0} value={params.comp.threshold}
                        onChange={e => setParams(p => ({ ...p, comp: { ...p.comp, threshold: parseInt(e.target.value) } }))} style={{ width: "100%" }} />
                    </label>
                    <label style={{ fontSize: 12 }}>Ratio: {params.comp.ratio}:1
                      <input type="range" min={1} max={20} value={params.comp.ratio}
                        onChange={e => setParams(p => ({ ...p, comp: { ...p.comp, ratio: parseInt(e.target.value) } }))} style={{ width: "100%" }} />
                    </label>
                    <label style={{ fontSize: 12 }}>Attack: {params.comp.attack} ms
                      <input type="range" min={0.1} max={50} step={0.1} value={params.comp.attack}
                        onChange={e => setParams(p => ({ ...p, comp: { ...p.comp, attack: parseFloat(e.target.value) } }))} style={{ width: "100%" }} />
                    </label>
                    <label style={{ fontSize: 12 }}>Release: {params.comp.release} ms
                      <input type="range" min={10} max={1000} value={params.comp.release}
                        onChange={e => setParams(p => ({ ...p, comp: { ...p.comp, release: parseInt(e.target.value) } }))} style={{ width: "100%" }} />
                    </label>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 12 }}>
                  <button onClick={handleProcess} disabled={loading} style={btnStyle(loading)}>Process Audio</button>
                  <button onClick={() => setParams(defaultParams)} style={{ ...btnStyle(false), background: "#334155" }}>Reset Defaults</button>
                </div>
              </div>
            )}

            {tab === "processed" && processResult && (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8, marginBottom: 16 }}>
                  <MetricCard label="RMS Level" value={processResult.analysis?.rms_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Peak Level" value={processResult.analysis?.peak_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Dynamic Range" value={processResult.analysis?.dynamic_range_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="SNR Estimate" value={processResult.analysis?.snr_estimate_db?.toFixed(1)} unit="dB" />
                  <MetricCard label="Speech" value={((processResult.analysis?.speech_likelihood_heuristic || 0) * 100).toFixed(0)} unit="%" />
                  <MetricCard label="Transcribability" value={((processResult.analysis?.transcribability_heuristic || 0) * 100).toFixed(0)} unit="%" />
                </div>
                {processResult.analysis?.spectrogram_url && (
                  <div style={{ marginBottom: 16 }}>
                    <h3 style={{ fontSize: 14, color: "#94a3b8", marginBottom: 8 }}>Processed Spectrogram</h3>
                    <img src={`${apiUrl}${processResult.analysis.spectrogram_url}`} alt="Processed" style={{ width: "100%", borderRadius: 8 }} />
                  </div>
                )}
                <div style={{ display: "flex", gap: 12 }}>
                  <button onClick={downloadProcessedAudio} style={btnStyle(false)}>Download Processed WAV</button>
                  <button onClick={handleTranscribe} disabled={loading} style={btnStyle(loading)}>Transcribe</button>
                </div>
              </div>
            )}

            {tab === "transcript" && transcript && (
              <div style={{ background: "#1e293b", borderRadius: 8, padding: 20 }}>
                <div style={{ display: "flex", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
                  <MetricCard label="Language" value={transcript.language} />
                  <MetricCard label="Confidence" value={(transcript.language_probability * 100).toFixed(0)} unit="%" />
                  <MetricCard label="Duration" value={transcript.duration?.toFixed(1)} unit="s" />
                  <MetricCard label="Words" value={transcript.word_count} />
                  {transcript.speakers?.length > 0 && <MetricCard label="Speakers" value={transcript.speakers.length} />}
                </div>
                <div style={{ background: "#0f172a", borderRadius: 8, padding: 16, maxHeight: 400, overflow: "auto" }}>
                  {transcript.segments?.map((seg, i) => (
                    <div key={i} style={{ marginBottom: 12, padding: 8, borderLeft: "3px solid #3b82f6" }}>
                      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>
                        [{seg.start?.toFixed(1)}s - {seg.end?.toFixed(1)}s]
                        {seg.speaker && <span style={{ color: "#22d3ee", marginLeft: 8 }}>{seg.speaker}</span>}
                        <span style={{ marginLeft: 8 }}>conf: {(seg.confidence * 100).toFixed(0)}%</span>
                      </div>
                      <div style={{ color: "#e2e8f0" }}>{seg.text}</div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 16, padding: 12, background: "#0f172a", borderRadius: 8 }}>
                  <h4 style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>Full Text</h4>
                  <p style={{ color: "#cbd5e1", lineHeight: 1.6 }}>{transcript.full_text}</p>
                </div>
              </div>
            )}

            {tab === "custody" && (
              <div style={{ background: "#1e293b", borderRadius: 8, padding: 20 }}>
                <h3 style={{ fontSize: 16, marginBottom: 16 }}>Chain of Custody</h3>
                <div style={{ fontFamily: "monospace", fontSize: 12, lineHeight: 1.8 }}>
                  <div><span style={{ color: "#64748b" }}>File:</span> {file?.name}</div>
                  <div><span style={{ color: "#64748b" }}>Size:</span> {file ? (file.size / 1024 / 1024).toFixed(2) + " MB" : "N/A"}</div>
                  <div><span style={{ color: "#64748b" }}>MD5:</span> {analysis?.file_hashes?.md5 || "N/A"}</div>
                  <div><span style={{ color: "#64748b" }}>SHA-256:</span> {analysis?.file_hashes?.sha256 || "N/A"}</div>
                  <div><span style={{ color: "#64748b" }}>Job ID:</span> {analysis?.job_id || "N/A"}</div>
                  <div><span style={{ color: "#64748b" }}>Analyzed:</span> {analysis ? new Date().toISOString() : "N/A"}</div>
                  {processResult && <div><span style={{ color: "#64748b" }}>Processed:</span> Job {processResult.job_id}</div>}
                  {transcript && <div><span style={{ color: "#64748b" }}>Transcribed:</span> {transcript.language} ({transcript.word_count} words)</div>}
                </div>
                <button onClick={downloadReport} style={{ ...btnStyle(false), marginTop: 16 }}>Export Full Report (JSON)</button>
              </div>
            )}

            {!loading && analysis && !processResult && tab === "analysis" && (
              <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
                <button onClick={() => setTab("params")} style={btnStyle(false)}>Configure & Process</button>
                <button onClick={handleTranscribe} disabled={loading} style={{ ...btnStyle(loading), background: "#7c3aed" }}>Transcribe Raw</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
