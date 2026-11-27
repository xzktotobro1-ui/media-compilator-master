using System.Text.Json;
using System.Text.Json.Serialization;

namespace RTXMediaMaster.Gui.Models;

public class Settings
{
    public string Theme { get; set; } = "dark"; // dark | light | system
    public string TargetFps { get; set; } = "120";
    public string Preset { get; set; } = "balanced"; // compact | balanced | quality
    public string Codec { get; set; } = "auto"; // auto | av1 | hevc | vvc | h264
    public bool Enhance { get; set; } = true;
    public string? Scale { get; set; } // null | 1920x1080 | ...
    public string? CropStart { get; set; } // hh:mm:ss
    public string? CropEnd { get; set; }
    public string AudioCodec { get; set; } = "copy"; // copy | aac | opus
    public string AudioBitrate { get; set; } = "192k";
    public bool NoSceneDetect { get; set; }
    public bool NoDeinterlace { get; set; }
    public bool NoColorMetadata { get; set; }
    public bool Verbose { get; set; }
    public int? Crf { get; set; }
    public double? Cq { get; set; }
    public int GpuIndex { get; set; } = 0;
    public int ChunkFrames { get; set; } = 96;
    public string? FfmpegPath { get; set; }
    public string? FfprobePath { get; set; }
    public string? RifePath { get; set; }
    public string? ModelsDir { get; set; }
    public string AfterCompletion { get; set; } = "none"; // none | notify | sleep | shutdown
    public string Language { get; set; } = "ru";

    [JsonIgnore]
    public bool UseCustomFfmpeg => !string.IsNullOrWhiteSpace(FfmpegPath);
    [JsonIgnore]
    public bool UseCustomFfprobe => !string.IsNullOrWhiteSpace(FfprobePath);
    [JsonIgnore]
    public bool UseCustomRife => !string.IsNullOrWhiteSpace(RifePath);
    [JsonIgnore]
    public bool UseCustomModelsDir => !string.IsNullOrWhiteSpace(ModelsDir);
}
