using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;
using RTXMediaMaster.Gui.ViewModels;

namespace RTXMediaMaster.Gui.Views;

public partial class DiagnosticsView
{
    private DiagnosticsViewModel? _vm;

    public DiagnosticsView()
    {
        InitializeComponent();
        // DataContext приходит из DataTemplate только после создания view
        DataContextChanged += (s, e) =>
        {
            if (_vm != null) _vm.PropertyChanged -= OnVmPropertyChanged;
            _vm = e.NewValue as DiagnosticsViewModel;
            if (_vm != null) _vm.PropertyChanged += OnVmPropertyChanged;
            UpdateGauge();
        };
        Loaded += (s, e) => UpdateGauge();
    }

    private void OnVmPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(DiagnosticsViewModel.GpuUtilization))
            Dispatcher.Invoke(UpdateGauge);
    }

    private void UpdateGauge()
    {
        if (GaugeArc == null || _vm == null) return;
        double pct = Math.Clamp(_vm.GpuUtilization, 0, 100);
        double sweep = pct / 100.0 * 360.0;
        double r = 60;
        var center = new Point(75, 75);
        double startAngle = -90;
        double endAngle = startAngle + sweep;
        Point start = PointOnCircle(center, r, startAngle);
        Point end = PointOnCircle(center, r, endAngle);
        bool largeArc = sweep > 180;

        var geometry = new StreamGeometry();
        using (var ctx = geometry.Open())
        {
            ctx.BeginFigure(start, false, false);
            if (sweep > 0.01)
                ctx.ArcTo(end, new Size(r, r), 0, largeArc, SweepDirection.Clockwise, true, false);
        }
        geometry.Freeze();
        GaugeArc.Data = geometry;
    }

    private static Point PointOnCircle(Point center, double radius, double angleDeg)
    {
        double rad = angleDeg * Math.PI / 180.0;
        return new Point(center.X + radius * Math.Cos(rad), center.Y + radius * Math.Sin(rad));
    }
}
