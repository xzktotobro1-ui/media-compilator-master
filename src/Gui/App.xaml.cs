using System.Windows;
using RTXMediaMaster.Gui.Services;
using RTXMediaMaster.Gui.ViewModels;

namespace RTXMediaMaster.Gui;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var settingsService = new SettingsService();
        var notification = new NotificationService();
        var updateService = new UpdateService();
        var engine = new EngineService(AppContext.BaseDirectory);
        var vm = new MainViewModel(settingsService, notification, updateService, engine);
        var main = new MainWindow(vm);
        main.Show();
    }
}
