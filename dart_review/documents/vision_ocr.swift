// macOS Vision text recognition for one image: one line per recognised text, tab separated:
// minX minY maxX maxY confidence text   (normalised 0-1, origin bottom-left, as Vision reports it)
// Used as a second, independent evidence source next to Tesseract (dart_review/documents/words.py).
import Foundation
import Vision

let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = false
let handler = VNImageRequestHandler(url: url)
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write("vision failed\n".data(using: .utf8)!)
    exit(2)
}
for observation in request.results ?? [] {
    guard let best = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    print(String(format: "%.5f\t%.5f\t%.5f\t%.5f\t%.3f\t", box.minX, box.minY, box.maxX, box.maxY, best.confidence) + best.string)
}
