using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using RTXMediaMaster.Gui.Models;
using RTXMediaMaster.Gui.Services;
using RTXMediaMaster.Gui.Views;

namespace RTXMediaMaster.Gui.ViewModels;

public enum AppPage
{
    Queue,
    Diagnostics,
    Settings,
    Log
}

public partial class MainViewModel : ObservableObject
{
    private readonly SettingsService _settingsService;
    private readonly NotificationService _notification;
    private readonly UpdateService _updateService;
    private readonly EngineService _engine;

    [ObservableProperty]
    private AppPage _currentPage = AppPage.Queue;

    [ObservableProperty]
    private object? _selectedPageViewModel;

    [ObservableProperty]
    private string _title = "RTX Media Master";

    [ObservableProperty]
    private string _versionBadge = "v3.5";

    [ObservableProperty]
    private string _gpuLabel = "Опрос GPU...";

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private string _statusText = "Готово";

    [ObservableProperty]
    private double _globalProgress;

    [ObservableProperty]
    private string _globalProgressText = "0%";

    [ObservableProperty]
    private int _activeStepIndex; // 0..4

    public QueueViewModel Queue { get; }
    public SettingsViewModel Settings { get; }
    public DiagnosticsViewModel Diagnostics { get; }
    public LogViewModel Log { get; }

    public MainViewModel(SettingsService settingsService,
        NotificationService notification, UpdateService updateService,
        EngineService engine)
    {
        _settingsService = settingsService;
        _notification = notification;
        _updateService = updateService;
        _engine = engine;

        Queue = new QueueViewModel(engine, notification, settingsService);
        Settings = new SettingsViewModel(settingsService);
        Diagnostics = new DiagnosticsViewModel();
        Log = new LogViewModel();

        // Прогресс движка → степпер и статус-бар
        _engine.ProgressChanged += (s, p) =>
        {
            Application.Current.Dispatcher.Invoke(() =>
            {
                int step = p.Stage switch
                {
                    "Анализ" => 0,
                    "Сцены" => 1,
                    "RIFE AI" => 2,
                    "Кодирование" => 3,
                    "Готово" => 4,
                    _ => ActiveStepIndex
                };
                SetStep(step);
                SetGlobalProgress(p.Percent, $"{p.Percent:0}%  {p.Message}");
            });
        };

        _engine.Completed += (s, r) =>
        {
            Application.Current.Dispatcher.Invoke(() =>
            {
                Log.SetCliCommand(_engine.LastCliCommand);
                if (r.Verification.Count > 0) Log.SetVerification(r.Verification);
                foreach (var line in r.LogLines)
                {
                    var lvl = line.Contains("ERROR", StringComparison.OrdinalIgnoreCase) ||
                              line.Contains("Traceback", StringComparison.OrdinalIgnoreCase)
                        ? LogLevel.Error
                        : line.Contains("WARNING", StringComparison.OrdinalIgnoreCase) ||
                          line.Contains("Внимание", StringComparison.OrdinalIgnoreCase)
                            ? LogLevel.Warning : LogLevel.Info;
                    Log.Add(line, lvl, "engine");
                }
            });
        };

        NavigateCommand = new RelayCommand<AppPage>(p =>
        {
            CurrentPage = p;
            SelectedPageViewModel = p switch
            {
                AppPage.Diagnostics => (object)Diagnostics,
                AppPage.Settings => Settings,
                AppPage.Log => Log,
                _ => Queue,
            };
        });
        StartCommand = new AsyncRelayCommand(StartAsync, () => !IsBusy && Queue.Items.Count > 0);
        CancelCommand = new RelayCommand(Cancel);
        OpenAboutCommand = new RelayCommand(OpenAbout);
        OpenHelpCommand = new RelayCommand(OpenHelp);
        CheckUpdatesCommand = new AsyncRelayCommand(CheckUpdatesAsync);
        ExitCommand = new RelayCommand(() => Application.Current.Shutdown());
        OpenSettingsFolderCommand = new RelayCommand(OpenSettingsFolder);
        OpenModelsFolderCommand = new RelayCommand(OpenModelsFolder);

        // Подписка на progresс очереди
        Queue.PropertyChanged += (s, e) =>
        {
            if (e.PropertyName == nameof(QueueViewModel.IsProcessing))
                OnPropertyChanged(nameof(IsProcessing));
        };
        Queue.Items.CollectionChanged += (s, e) => ((CommunityToolkit.Mvvm.Input.AsyncRelayCommand)StartCommand).NotifyCanExecuteChanged();

        // Первая вкладка отображается сразу после запуска
        SelectedPageViewModel = Queue;
    }

    public bool IsProcessing => Queue.IsProcessing;

    public ICommand NavigateCommand { get; }
    public ICommand StartCommand { get; }
    public ICommand CancelCommand { get; }
    public ICommand OpenAboutCommand { get; }
    public ICommand OpenHelpCommand { get; }
    public ICommand CheckUpdatesCommand { get; }
    public ICommand ExitCommand { get; }
    public ICommand OpenSettingsFolderCommand { get; }
    public ICommand OpenModelsFolderCommand { get; }

    private async Task StartAsync()
    {
        if (Queue.Items.Count == 0) return;
        IsBusy = true;
        StatusText = "Обработка очереди...";
        try
        {
            await Queue.StartAllAsync();
            StatusText = "Очередь обработана";
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private void Cancel()
    {
        _engine.Cancel();
        Queue.CancelAll();
        StatusText = "Отменено пользователем";
        Log.Add("Обработка прервана пользователем", LogLevel.Warning);
    }

    private void OpenAbout()
    {
        var dlg = new AboutDialog { Owner = Application.Current.MainWindow };
        dlg.ShowDialog();
    }

    private async Task CheckUpdatesAsync()
    {
        StatusText = "Проверка обновлений...";
        try
        {
            var info = await _updateService.CheckAsync();
            if (!string.IsNullOrEmpty(info.Error))
            {
                StatusText = $"Ошибка проверки: {info.Error}";
                return;
            }
            if (info.Available)
            {
                _notification.Show("Доступно обновление", $"Версия {info.LatestVersion}");
                StatusText = $"Доступна версия {info.LatestVersion}";
            }
            else
            {
                StatusText = "Установлена последняя версия";
            }
        }
        catch (Exception ex)
        {
            StatusText = $"Ошибка: {ex.Message}";
        }
    }

    private void OpenHelp()
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = "https://github.com/xzktotobro1-ui/media-compilator-master#readme",
                UseShellExecute = true
            });
        }
        catch { }
    }

    private void OpenSettingsFolder()
    {
        try { System.Diagnostics.Process.Start("explorer.exe", _settingsService.AppDataDir); } catch { }
    }

    private void OpenModelsFolder()
    {
        var dir = System.IO.Path.Combine(AppContext.BaseDirectory, "models");
        if (!System.IO.Directory.Exists(dir))
            dir = _settingsService.AppDataDir;
        try { System.Diagnostics.Process.Start("explorer.exe", dir); } catch { }
    }

    public void SetGpuInfo(string name, double utilization, double vramUsed, double vramTotal)
    {
        GpuLabel = vramTotal > 0
            ? $"{name} • {(int)utilization}% • {vramUsed:0.##}/{vramTotal:0.##} GB"
            : $"{name} • {(int)utilization}%";
    }

    public void SetStep(int index)
    {
        ActiveStepIndex = Math.Clamp(index, 0, 4);
        StatusText = index switch
        {
            0 => "Анализ",
            1 => "Сцены",
            2 => "RIFE AI",
            3 => "Кодирование",
            _ => "Готово"
        };
    }

    public void SetGlobalProgress(double pct, string text)
    {
        GlobalProgress = pct;
        GlobalProgressText = text;
    }
}

public partial class QueueViewModel : ObservableObject
{
    private readonly EngineService _engine;
    private readonly NotificationService _notification;
    private readonly SettingsService _settingsService;

    [ObservableProperty]
    private ObservableCollection<QueueItemViewModel> _items = new();

    [ObservableProperty]
    private bool _isProcessing;

    [ObservableProperty]
    private string _targetFps = "120";

    [ObservableProperty]
    private string _preset = "balanced";

    [ObservableProperty]
    private string _codec = "auto";

    [ObservableProperty]
    private bool _enhance = true;

    [ObservableProperty]
    private string _afterCompletion = "none"; // none | notify | sleep | shutdown

    [ObservableProperty]
    private string _searchText = string.Empty;

    public System.ComponentModel.ICollectionView FilteredItems { get; }

    public bool IsEmpty => Items.Count == 0;

    public ObservableCollection<KeyValuePair<string, string>> AfterCompletionItems { get; } = new()
    {
        new KeyValuePair<string,string>("Ничего","none"),
        new KeyValuePair<string,string>("Уведомление Windows","notify"),
        new KeyValuePair<string,string>("Спящий режим","sleep"),
        new KeyValuePair<string,string>("Выключить ПК","shutdown"),
    };

    public bool IsFps60 { get => TargetFps == "60"; set { if (value) TargetFps = "60"; } }
    public bool IsFps120 { get => TargetFps == "120"; set { if (value) TargetFps = "120"; } }
    public bool IsFps2x { get => TargetFps == "2x"; set { if (value) TargetFps = "2x"; } }
    public bool IsFps3x { get => TargetFps == "3x"; set { if (value) TargetFps = "3x"; } }

    public bool IsPresetCompact { get => Preset == "compact"; set { if (value) Preset = "compact"; } }
    public bool IsPresetBalanced { get => Preset == "balanced"; set { if (value) Preset = "balanced"; } }
    public bool IsPresetQuality { get => Preset == "quality"; set { if (value) Preset = "quality"; } }

    public bool IsCodecAuto { get => Codec == "auto"; set { if (value) Codec = "auto"; } }
    public bool IsCodecAv1 { get => Codec == "av1"; set { if (value) Codec = "av1"; } }
    public bool IsCodecHevc { get => Codec == "hevc"; set { if (value) Codec = "hevc"; } }

    public bool IsAfterNone { get => AfterCompletion == "none"; set { if (value) AfterCompletion = "none"; } }
    public bool IsAfterNotify { get => AfterCompletion == "notify"; set { if (value) AfterCompletion = "notify"; } }
    public bool IsAfterSleep { get => AfterCompletion == "sleep"; set { if (value) AfterCompletion = "sleep"; } }
    public bool IsAfterShutdown { get => AfterCompletion == "shutdown"; set { if (value) AfterCompletion = "shutdown"; } }

    public QueueViewModel(EngineService engine, NotificationService notification, SettingsService settingsService)
    {
        _engine = engine;
        _notification = notification;
        _settingsService = settingsService;

        FilteredItems = System.Windows.Data.CollectionViewSource.GetDefaultView(Items);
        FilteredItems.Filter = obj =>
        {
            if (obj is not QueueItemViewModel item) return false;
            if (string.IsNullOrWhiteSpace(SearchText)) return true;
            return item.FileName.IndexOf(SearchText, StringComparison.OrdinalIgnoreCase) >= 0;
        };
        PropertyChanged += (s, e) => { if (e.PropertyName == nameof(SearchText)) FilteredItems.Refresh(); };

        AddFilesCommand = new RelayCommand(AddFiles);
        AddFolderCommand = new RelayCommand(AddFolder);
        RemoveItemCommand = new RelayCommand<QueueItemViewModel>(x => { if (x != null) Items.Remove(x); OnPropertyChanged(nameof(IsEmpty)); });
        ClearCommand = new RelayCommand(() => { Items.Clear(); OnPropertyChanged(nameof(IsEmpty)); });
        StartAllCommand = new AsyncRelayCommand(StartAllAsync, () => !IsProcessing && Items.Count > 0);
        CancelAllCommand = new RelayCommand(CancelAll);
        OpenPresetManagerCommand = new RelayCommand(OpenPresetManager);

        Items.CollectionChanged += (s, e) =>
        {
            OnPropertyChanged(nameof(IsEmpty));
            ((CommunityToolkit.Mvvm.Input.AsyncRelayCommand)StartAllCommand).NotifyCanExecuteChanged();
        };
    }

    public ICommand AddFilesCommand { get; }
    public ICommand AddFolderCommand { get; }
    public ICommand RemoveItemCommand { get; }
    public ICommand ClearCommand { get; }
    public ICommand StartAllCommand { get; }
    public ICommand CancelAllCommand { get; }
    public ICommand OpenPresetManagerCommand { get; }

    public void AddItem(string filePath)
    {
        if (Items.Any(i => i.SourcePath.Equals(filePath, StringComparison.OrdinalIgnoreCase)))
            return;
        var vm = new QueueItemViewModel(filePath, _engine, _settingsService);
        Items.Add(vm);
        OnPropertyChanged(nameof(IsEmpty));
    }

    private void AddFiles()
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Multiselect = true,
            Filter = "Видео (*.mp4;*.mkv;*.mov;*.avi;*.webm)|*.mp4;*.mkv;*.mov;*.avi;*.webm|Все файлы (*.*)|*.*"
        };
        if (dlg.ShowDialog() == true)
            foreach (var f in dlg.FileNames) AddItem(f);
    }

    private void AddFolder()
    {
        var dlg = new Ookii.Dialogs.Wpf.VistaFolderBrowserDialog();
        if (dlg.ShowDialog(Application.Current.MainWindow) == true)
        {
            var exts = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".mp4", ".mkv", ".mov", ".avi", ".webm" };
            foreach (var f in System.IO.Directory.GetFiles(dlg.SelectedPath, "*.*", System.IO.SearchOption.AllDirectories)
                         .Where(p => exts.Contains(System.IO.Path.GetExtension(p))))
                AddItem(f);
        }
    }

    public void CancelAll()
    {
        _engine.Cancel();
        IsProcessing = false;
        foreach (var i in Items) i.Cancel();
    }

    public void ApplyPreset(string targetFps, string preset, string codec, bool enhance, string afterCompletion)
    {
        TargetFps = targetFps;
        Preset = preset;
        Codec = codec;
        Enhance = enhance;
        AfterCompletion = afterCompletion;
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(TargetFps)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsFps60)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsFps120)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsFps2x)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsFps3x)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsPresetCompact)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsPresetBalanced)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsPresetQuality)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsCodecAuto)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsCodecAv1)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsCodecHevc)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(Enhance)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsAfterNone)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsAfterNotify)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsAfterSleep)));
        OnPropertyChanged(new System.ComponentModel.PropertyChangedEventArgs(nameof(IsAfterShutdown)));
    }

    public async Task StartAllAsync()
    {
        IsProcessing = true;
        try
        {
            var settings = _settingsService.Load();
            settings.TargetFps = TargetFps;
            settings.Preset = Preset;
            settings.Codec = Codec;
            settings.Enhance = Enhance;
            settings.AfterCompletion = AfterCompletion;
            _settingsService.Save(settings);

            foreach (var item in Items.Where(i => i.Status != Models.ItemStatus.Completed && i.Status != Models.ItemStatus.Error))
            {
                if (item.Status == Models.ItemStatus.Removed) continue;
                await item.ProcessAsync(settings);
            }

            // Действие после завершения
            switch (AfterCompletion)
            {
                case "notify": _notification.Show("RTX Media Master", "Обработка очереди завершена"); break;
                case "sleep": new NotificationService().Sleep(); break;
                case "shutdown": new NotificationService().Shutdown(); break;
            }
        }
        finally
        {
            IsProcessing = false;
        }
    }

    private void OpenPresetManager()
    {
        var dlg = new Views.PresetManagerDialog { Owner = Application.Current.MainWindow };
        dlg.ShowDialog();
    }
}

public partial class QueueItemViewModel : ObservableObject
{
    private readonly EngineService _engine;
    private readonly SettingsService _settingsService;
    private readonly string _sourcePath;

    private readonly Models.QueueItem _model = new();

    public string SourcePath
    {
        get => _model.SourcePath;
        set
        {
            _model.SourcePath = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(FileName));
        }
    }

    public string FileName => _model.FileName;
    public string? OutputPath => _model.OutputPath;
    public System.Windows.Media.ImageSource? Thumbnail => _model.Thumbnail;
    public string ResolutionLabel => _model.ResolutionLabel;
    public string SizeText => _model.SizeText;
    public string DurationText => _model.DurationText;
    public bool IsVfr => _model.IsVfr;

    public Models.ItemStatus Status
    {
        get => _model.Status;
        set
        {
            _model.Status = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(CanTest));
            OnPropertyChanged(nameof(CanRemove));
        }
    }

    public double Progress
    {
        get => _model.Progress;
        set { _model.Progress = value; OnPropertyChanged(); }
    }

    public string ProgressText
    {
        get => _model.ProgressText;
        set { _model.ProgressText = value; OnPropertyChanged(); }
    }

    public string Stage
    {
        get => _model.Stage;
        set { _model.Stage = value; OnPropertyChanged(); }
    }

    public string? Error
    {
        get => _model.Error;
        set { _model.Error = value; OnPropertyChanged(); }
    }

    public bool CanTest => Status == Models.ItemStatus.Ready || Status == Models.ItemStatus.Completed;
    public bool CanRemove => Status != Models.ItemStatus.Processing;
    public bool IsProcessing => Status == Models.ItemStatus.Processing;

    public QueueItemViewModel(string sourcePath, EngineService engine, SettingsService settingsService)
    {
        _sourcePath = sourcePath;
        _engine = engine;
        _settingsService = settingsService;
        _model.SourcePath = sourcePath;
        Status = Models.ItemStatus.Pending;
        Stage = "Ожидание";
        AnalyzeCommand = new AsyncRelayCommand(AnalyzeAsync);
        TestCommand = new RelayCommand(Test);
        OpenFolderCommand = new RelayCommand(OpenFolder);
        RemoveCommand = new RelayCommand(() => { Status = Models.ItemStatus.Removed; });
    }

    public ICommand AnalyzeCommand { get; }
    public ICommand TestCommand { get; }
    public ICommand OpenFolderCommand { get; }
    public ICommand RemoveCommand { get; }

    private async Task AnalyzeAsync()
    {
        Status = Models.ItemStatus.Analyzing;
        Stage = "Анализ";
        try
        {
            var settings = _settingsService.Load();
            var ffmpeg = settings.UseCustomFfmpeg ? settings.FfmpegPath! :
                         System.IO.Path.Combine(AppContext.BaseDirectory, "ffmpeg.exe");
            var ffprobe = settings.UseCustomFfprobe ? settings.FfprobePath! :
                          System.IO.Path.Combine(AppContext.BaseDirectory, "ffprobe.exe");
            if (!System.IO.File.Exists(ffprobe)) ffprobe = "ffprobe";
            if (!System.IO.File.Exists(ffmpeg)) ffmpeg = "ffmpeg";

            var probe = new Services.ProbeService(ffprobe);
            var info = await probe.ProbeAsync(_sourcePath);

            _model.Width = info.Width;
            _model.Height = info.Height;
            _model.SourceFps = info.Fps;
            _model.SourceCodec = info.Codec;
            _model.DurationSeconds = info.DurationSeconds;
            _model.SizeBytes = info.SizeBytes;
            _model.IsVfr = info.IsVfr;
            _model.TargetCodec = settings.Codec.ToUpperInvariant();
            _model.TargetFps = double.TryParse(_settingsService.Load().TargetFps, out var tf) ? tf : 120;

            // Превью
            var thumbDir = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "RTXMediaMaster", "thumbs");
            System.IO.Directory.CreateDirectory(thumbDir);
            var thumbPath = System.IO.Path.Combine(thumbDir, $"{System.IO.Path.GetFileNameWithoutExtension(_sourcePath)}_{Guid.NewGuid():N}.png");
            var thumb = new Services.ThumbnailService(ffmpeg);
            var tp = await thumb.ExtractAsync(_sourcePath, thumbPath);
            if (tp != null)
            {
                var bmp = new System.Windows.Media.Imaging.BitmapImage();
                bmp.BeginInit();
                bmp.UriSource = new Uri(tp);
                bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
                bmp.EndInit();
                bmp.Freeze();
                _model.Thumbnail = bmp;
            }

            Status = Models.ItemStatus.Ready;
            Stage = "Готов к обработке";
        }
        catch (Exception ex)
        {
            Status = Models.ItemStatus.Error;
            Error = ex.Message;
            Stage = "Ошибка анализа";
        }
    }

    public async Task ProcessAsync(Models.Settings settings)
    {
        Status = Models.ItemStatus.Processing;
        Stage = "Анализ";
        Progress = 0;
        Error = null;
        try
        {
            var result = await _engine.RunAsync(_model, settings);
            if (result.Success)
            {
                Status = Models.ItemStatus.Completed;
                Stage = "Готово";
                Progress = 100;
                _model.OutputPath = result.OutputPath;
            }
            else if (result.Cancelled)
            {
                Status = Models.ItemStatus.Cancelled;
                Stage = "Отменено";
            }
            else
            {
                Status = Models.ItemStatus.Error;
                Error = result.ErrorMessage ?? $"Код завершения {result.ExitCode}";
                Stage = "Ошибка";
            }
        }
        catch (Exception ex)
        {
            Status = Models.ItemStatus.Error;
            Error = ex.Message;
            Stage = "Ошибка";
        }
    }

    public void Cancel()
    {
        if (Status == Models.ItemStatus.Processing)
        {
            Status = Models.ItemStatus.Cancelled;
            Stage = "Отменено";
        }
    }

    private async void Test()
    {
        Status = Models.ItemStatus.Analyzing;
        Stage = "Тест 5 сек: рендер...";
        try
        {
            var settings = _settingsService.Load();
            var ffmpeg = settings.UseCustomFfmpeg ? settings.FfmpegPath! :
                         System.IO.Path.Combine(AppContext.BaseDirectory, "ffmpeg.exe");
            if (!System.IO.File.Exists(ffmpeg)) ffmpeg = "ffmpeg";

            var tempDir = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "RTXMediaMaster", "previews");
            System.IO.Directory.CreateDirectory(tempDir);
            var before = System.IO.Path.Combine(tempDir, $"before_{Guid.NewGuid():N}.mp4");
            var after = System.IO.Path.Combine(tempDir, $"after_{Guid.NewGuid():N}.mp4");

            // 1) Нарезаем 5-секундный фрагмент оригинала (без перекодирования)
            var cutArgs = $"-hide_banner -loglevel error -y -i \"{_sourcePath}\" -t 5 -c copy \"{before}\"";
            var cutOk = await RunProcessAsync(ffmpeg, cutArgs);
            if (!cutOk || !System.IO.File.Exists(before))
                throw new InvalidOperationException("Не удалось создать фрагмент оригинала.");

            // 2) Прогоняем фрагмент через движок с теми же настройками
            var testSettings = new Models.Settings
            {
                TargetFps = settings.TargetFps, Preset = settings.Preset, Codec = settings.Codec,
                Enhance = settings.Enhance, Scale = settings.Scale, GpuIndex = settings.GpuIndex,
                ChunkFrames = settings.ChunkFrames, AudioCodec = settings.AudioCodec,
                AudioBitrate = settings.AudioBitrate, NoSceneDetect = settings.NoSceneDetect,
                NoDeinterlace = settings.NoDeinterlace, NoColorMetadata = settings.NoColorMetadata,
                FfmpegPath = settings.FfmpegPath, FfprobePath = settings.FfprobePath,
                RifePath = settings.RifePath, ModelsDir = settings.ModelsDir,
                Crf = settings.Crf, Cq = settings.Cq
            };
            var testItem = new Models.QueueItem
            {
                SourcePath = before,
                Width = _model.Width, Height = _model.Height,
                SourceFps = _model.SourceFps, SourceCodec = _model.SourceCodec,
                DurationSeconds = 5, SizeBytes = _model.SizeBytes
            };

            var result = await _engine.RunAsync(testItem, testSettings);
            if (result.Success && System.IO.File.Exists(result.OutputPath))
                System.IO.File.Copy(result.OutputPath, after, true);
            else if (System.IO.File.Exists(before))
                System.IO.File.Copy(before, after, true);

            Stage = "Тест готов";
            var dlg = new Views.CompareDialog(before, after)
            {
                Owner = Application.Current.MainWindow
            };
            dlg.Show();
        }
        catch (Exception ex)
        {
            Error = ex.Message;
            Stage = "Ошибка теста";
        }
        finally
        {
            Status = Models.ItemStatus.Ready;
        }
    }

    private static async System.Threading.Tasks.Task<bool> RunProcessAsync(string file, string args)
    {
        try
        {
            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = file, Arguments = args, UseShellExecute = false,
                CreateNoWindow = true, RedirectStandardError = true
            };
            using var p = System.Diagnostics.Process.Start(psi);
            if (p == null) return false;
            var err = await p.StandardError.ReadToEndAsync();
            await p.WaitForExitAsync();
            return p.ExitCode == 0;
        }
        catch { return false; }
    }

    private void OpenFolder()
    {
        try
        {
            var dir = System.IO.Path.GetDirectoryName(_sourcePath);
            if (!string.IsNullOrEmpty(dir)) System.Diagnostics.Process.Start("explorer.exe", dir);
        }
        catch { }
    }
}
