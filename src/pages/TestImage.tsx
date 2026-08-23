import React, { useState } from "react";
import { Header } from "../Layout";
import type { ParkingResult } from "../types";

export function TestImage() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState<ParkingResult | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validTypes = ["image/jpeg", "image/png", "image/webp"];
      if (!validTypes.includes(file.type)) {
        alert("Unsupported file type. Please upload a JPG, PNG, or WEBP image.");
        return;
      }
      setSelectedFile(file);
      const url = URL.createObjectURL(file);
      setPreviewUrl(url);
      setResult(null); 
    }
  };

  const handleProcess = async () => {
    if (!selectedFile) return;
    setIsProcessing(true);
    setResult(null);

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
    // 2-minute timeout to accommodate slow EasyOCR on CPU (no GPU available)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 120000);
      
      const response = await fetch("/api/anpr/image", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      
      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error("Failed to process image");
      }

      const data = await response.json();
      setResult(data);
    } catch (err: any) {
      console.error(err);
      if (err.name === 'AbortError') {
        setResult({
          success: false,
          plate_detected: false,
          ocr_success: false,
          plate_number: "",
          source: "image_upload",
          status: "TIMEOUT",
          timestamp: new Date().toISOString(),
        } as any);
      } else {
        setResult({
          success: false,
          plate_detected: false,
          ocr_success: false,
          plate_number: "",
          source: "image_upload",
          status: "CONNECTION_ERROR",
          timestamp: new Date().toISOString(),
        } as any);
      }
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <>
      <Header
        title="Test ANPR with Image"
        note="Upload a vehicle or number plate image to test the ANPR pipeline."
      />

      <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", padding: "1rem" }}>
        
        <section className="card" style={{ flex: "1 1 400px", maxWidth: "600px" }}>
          <h2>📷 Upload Image</h2>
          <p className="eyebrow" style={{ marginBottom: "1rem" }}>
            Supported: JPG, JPEG, PNG, WEBP
          </p>

          <input
            type="file"
            accept="image/jpeg, image/png, image/webp"
            onChange={handleFileChange}
            style={{ marginBottom: "1rem", display: "block" }}
          />

          {previewUrl && (
            <div style={{ marginBottom: "1rem" }}>
              <img
                src={previewUrl}
                alt="Upload preview"
                style={{
                  width: "100%",
                  maxHeight: "300px",
                  objectFit: "contain",
                  borderRadius: "8px",
                  background: "#000",
                }}
              />
            </div>
          )}

          <button
            className="primary"
            onClick={handleProcess}
            disabled={!selectedFile || isProcessing}
            style={{ width: "100%", padding: "12px", fontSize: "16px" }}
          >
            {isProcessing ? "Processing..." : "🔍 Analyze Number Plate"}
          </button>
        </section>

        {result && (
          <section className="card" style={{ flex: "1 1 400px", maxWidth: "600px" }}>
            <h2>🔍 DETECTION RESULT</h2>
            
            {result.processedImage && (
              <div style={{ marginBottom: "1rem" }}>
                <img
                  src={result.processedImage}
                  alt="YOLO Bounding Box"
                  style={{
                    width: "100%",
                    maxHeight: "300px",
                    objectFit: "contain",
                    borderRadius: "8px",
                    background: "#000",
                  }}
                />
              </div>
            )}

            {!result.plate_detected ? (
              <div style={{ padding: "1rem", background: "rgba(255, 0, 0, 0.1)", borderRadius: "8px", border: "1px solid rgba(255, 0, 0, 0.2)" }}>
                <h3 style={{ color: "#ff4444", margin: 0 }}>❌ No License Plate Detected</h3>
                <p style={{ margin: "8px 0 0 0", opacity: 0.8 }}>Please upload a clearer vehicle or number-plate image.</p>
              </div>
            ) : !result.ocr_success ? (
              <div style={{ padding: "1rem", background: "rgba(255, 165, 0, 0.1)", borderRadius: "8px", border: "1px solid rgba(255, 165, 0, 0.2)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h3 style={{ color: "#ffa500", margin: 0 }}>⚠️ License Plate Detected</h3>
                  <button onClick={handleProcess} className="secondary" style={{ padding: "4px 8px", fontSize: "12px", background: "transparent", border: "1px solid #ffa500", color: "#ffa500", cursor: "pointer", borderRadius: "4px" }} disabled={isProcessing}>
                    {isProcessing ? "🔄 Retrying..." : "🔄 Retry OCR"}
                  </button>
                </div>
                <p style={{ margin: "8px 0 12px 0", opacity: 0.9 }}><strong>OCR: Unable to confidently read plate</strong></p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                  <div>
                    <span className="eyebrow" style={{ display: "block" }}>YOLO Conf</span>
                    <strong>{Math.round((result.yolo_confidence || 0) * 100)}%</strong>
                  </div>
                  <div>
                    <span className="eyebrow" style={{ display: "block" }}>Engine</span>
                    <strong style={{ textTransform: "capitalize" }}>{result.ocr_engine || "Tesseract/EasyOCR"}</strong>
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginTop: "12px" }}>
                    {result.original_crop && (
                      <div style={{display: 'flex', flexDirection: 'column'}}>
                        <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>Raw Crop</span>
                        <div style={{ flex: 1, background: '#000', borderRadius: '4px', display: 'flex', alignItems: 'center', padding: '4px', border: "1px solid #333" }}>
                          <img src={result.original_crop} style={{ width: "100%", maxHeight: "80px", objectFit: "contain" }} alt="Raw" />
                        </div>
                      </div>
                    )}
                    {result.preprocessed_crop && (
                      <div style={{display: 'flex', flexDirection: 'column'}}>
                        <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>OCR Input (Preprocessed)</span>
                        <div style={{ flex: 1, background: '#000', borderRadius: '4px', display: 'flex', alignItems: 'center', padding: '4px', border: "1px solid #333" }}>
                          <img src={result.preprocessed_crop} style={{ width: "100%", maxHeight: "80px", objectFit: "contain" }} alt="Preprocessed" />
                        </div>
                      </div>
                    )}
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
                <div style={{ padding: "1rem", background: "rgba(0, 255, 0, 0.1)", borderRadius: "8px", border: "1px solid rgba(0, 255, 0, 0.2)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                    <h3 style={{ color: "#44ff44", margin: 0 }}>🚗 License Plate Detected</h3>
                    <button onClick={handleProcess} className="secondary" style={{ padding: "4px 8px", fontSize: "12px", background: "transparent", border: "1px solid #44ff44", color: "#44ff44", cursor: "pointer", borderRadius: "4px" }} disabled={isProcessing}>
                      {isProcessing ? "🔄 Retrying..." : "🔄 Retry OCR"}
                    </button>
                  </div>
                  
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginTop: "1rem" }}>
                    <div>
                      <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>License Plate</span>
                      <strong style={{ fontSize: "28px", letterSpacing: "2px", display: "flex", alignItems: "center", gap: "12px" }}>
                        {result.plate_number} 
                        {result.is_valid_indian_format ? 
                          <span title="Valid Indian Format" style={{fontSize:"18px"}}>✅</span> : 
                          <span title="Unknown Format" style={{fontSize:"18px", opacity: 0.5}}>❓</span>}
                      </strong>
                    </div>
                    
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem" }}>
                      <div>
                        <span className="eyebrow" style={{ display: "block" }}>YOLO Conf</span>
                        <strong>{Math.round((result.yolo_confidence || 0) * 100)}%</strong>
                      </div>
                      <div>
                        <span className="eyebrow" style={{ display: "block" }}>OCR Conf</span>
                        <strong>{Math.round((result.ocr_confidence || 0) * 100)}%</strong>
                      </div>
                      <div>
                        <span className="eyebrow" style={{ display: "block" }}>Engine</span>
                        <strong style={{ textTransform: "capitalize" }}>{result.ocr_engine || "Tesseract"}</strong>
                      </div>
                    </div>

                    {/* Debug Crops */}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginTop: "12px" }}>
                        {result.original_crop && (
                          <div style={{display: 'flex', flexDirection: 'column'}}>
                            <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>Raw Crop</span>
                            <div style={{ flex: 1, background: '#000', borderRadius: '4px', display: 'flex', alignItems: 'center', padding: '4px', border: "1px solid #333" }}>
                              <img src={result.original_crop} style={{ width: "100%", maxHeight: "80px", objectFit: "contain" }} alt="Raw" />
                            </div>
                          </div>
                        )}
                        {result.preprocessed_crop && (
                          <div style={{display: 'flex', flexDirection: 'column'}}>
                            <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>OCR Input (Preprocessed)</span>
                            <div style={{ flex: 1, background: '#000', borderRadius: '4px', display: 'flex', alignItems: 'center', padding: '4px', border: "1px solid #333" }}>
                              <img src={result.preprocessed_crop} style={{ width: "100%", maxHeight: "80px", objectFit: "contain" }} alt="Preprocessed" />
                            </div>
                          </div>
                        )}
                    </div>
                  </div>
                </div>

                <div style={{ padding: "1rem", background: "var(--bg-elevated)", borderRadius: "8px", border: "1px solid var(--border)" }}>
                  <div style={{ marginBottom: "12px" }}>
                    <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>Parking Status</span>
                    <strong style={{ 
                      fontSize: "16px",
                      color: result.status === 'GRANTED' ? '#44ff44' : 
                             result.status === 'ALREADY_PARKED' ? '#ffa500' : 
                             result.status === 'COOLDOWN' ? '#ffa500' :
                             '#ff4444' 
                    }}>
                      {result.status === 'GRANTED' ? '🟢 GRANTED' : 
                       result.status === 'ALREADY_PARKED' ? '🔴 ALREADY PARKED' : 
                       result.status === 'COOLDOWN' ? '🟡 ON COOLDOWN' :
                       result.status}
                    </strong>
                  </div>
                  {result.slot && result.slot !== "N/A" && (
                    <div>
                      <span className="eyebrow" style={{ display: "block", marginBottom: "4px" }}>Parking Slot</span>
                      <strong style={{fontSize: "20px"}}>{result.slot}</strong>
                    </div>
                  )}
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </>
  );
}
