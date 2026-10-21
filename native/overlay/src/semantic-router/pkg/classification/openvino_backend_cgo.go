//go:build openvino && !windows && cgo

package classification

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"

	openvino_binding "github.com/vllm-project/semantic-router/openvino-binding"
)

// embeddingBackendOverride reads the EMBEDDING_BACKEND_OVERRIDE env var (normalized).
func embeddingBackendOverride() string {
	return strings.ToLower(strings.TrimSpace(os.Getenv("EMBEDDING_BACKEND_OVERRIDE")))
}

// resolveOpenVINOModelPath converts a directory path to the actual .xml model file.
// If the path already ends in .xml, it is returned as-is.
// Otherwise it looks for openvino/openvino_model.xml or openvino_model.xml in the directory.
func resolveOpenVINOModelPath(modelPath string) string {
	if strings.HasSuffix(modelPath, ".xml") {
		return modelPath
	}
	candidates := []string{
		filepath.Join(modelPath, "openvino", "openvino_model.xml"),
		filepath.Join(modelPath, "openvino_model.xml"),
	}
	for _, c := range candidates {
		if _, err := os.Stat(c); err == nil {
			return c
		}
	}
	return modelPath
}

func initOpenVINOModel(modelType, mmBertModelPath, fallbackModelPath string, useCPU bool) error {
	if path := os.Getenv("OPENVINO_EMBEDDING_MODEL_PATH"); path != "" {
		mmBertModelPath = path
	}
	device := "AUTO"
	if useCPU {
		device = "CPU"
	}

	switch strings.ToLower(strings.TrimSpace(modelType)) {
	case "mmbert", "modernbert":
		if mmBertModelPath == "" {
			return fmt.Errorf("embedding backend openvino with model_type=%s requires mmbert_model_path", modelType)
		}
		return openvino_binding.InitModernBertEmbedding(resolveOpenVINOModelPath(mmBertModelPath), device)
	default:
		modelPath := fallbackModelPath
		if modelPath == "" {
			modelPath = mmBertModelPath
		}
		if modelPath == "" {
			return fmt.Errorf("embedding backend openvino requires model path")
		}
		return openvino_binding.InitEmbeddingModel(resolveOpenVINOModelPath(modelPath), device)
	}
}

// maxTokenLength is the max input sequence length for ModernBERT tokenization.
// This is distinct from targetDim (output embedding dimension) which is model-determined.
const maxTokenLength = 32768

func getOpenVINOEmbedding(modelType, text string, targetDim int) ([]float32, error) {
	var embedding []float32
	var err error
	switch strings.ToLower(strings.TrimSpace(modelType)) {
	case "mmbert", "modernbert":
		embedding, err = openvino_binding.GetModernBertEmbedding(text, maxTokenLength)
	default:
		embedding, err = openvino_binding.GetEmbedding(text, maxTokenLength)
	}
	if err != nil {
		return nil, err
	}
	if targetDim > 0 && targetDim < len(embedding) {
		embedding = embedding[:targetDim]
	}
	// Complexity computes dot products assuming unit vectors, as Candle returns.
	var squaredNorm float64
	for _, value := range embedding {
		squaredNorm += float64(value) * float64(value)
	}
	if squaredNorm == 0 || math.IsNaN(squaredNorm) || math.IsInf(squaredNorm, 0) {
		return nil, fmt.Errorf("invalid OpenVINO embedding norm: %v", squaredNorm)
	}
	norm := math.Sqrt(squaredNorm)
	for i := range embedding {
		embedding[i] = float32(float64(embedding[i]) / norm)
	}
	return embedding, nil
}

func initOpenVINOClassifier(modelPath string, numClasses int, useCPU bool) error {
	device := "AUTO"
	if useCPU {
		device = "CPU"
	}
	resolved := resolveOpenVINOModelPath(modelPath)
	return openvino_binding.InitModernBertClassifier(resolved, numClasses, device)
}

func classifyOpenVINO(text string) (openvino_binding.ClassResult, error) {
	return openvino_binding.ClassifyModernBert(text)
}
