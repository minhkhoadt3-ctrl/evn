// Main Application Logic
class ElectricityApp {
    constructor() {
        this.dataManager = new DataManager();
        this.chartManager = new ChartManager();
        this.uiManager = new UIManager();
        this.currentYear = new Date().getFullYear();
        this.comparisonChartType = localStorage.getItem('comparisonChartType') || 'bar';
        this.comparisonShowLabels = localStorage.getItem('comparisonShowLabels') === 'true';


        this.init();
    } async init() {
        try {
            this.uiManager.showLoader(true);
            await this.loadAccounts();
            this.setupEventListeners();

            // Khởi tạo ô kết quả tìm kiếm với thông báo mặc định
            this.uiManager.initializeSearchResults();

            // Delay restore để đảm bảo tất cả select elements đã được populate và DOM stable
            setTimeout(async () => {
                this.restoreUIState();
                // Trigger load data after restore để đảm bảo data sync với UI
                await this.loadDataForAccount();
            }, 500);
        } catch (error) {
            console.error('Lỗi khởi tạo ứng dụng:', error);
            this.uiManager.showToast('Không thể khởi tạo ứng dụng. Vui lòng kiểm tra kết nối và thử lại.', 'error');
        } finally {
            this.uiManager.showLoader(false);
        }
    } async loadAccounts() {
        try {
            const accounts = await this.dataManager.loadAccounts();
            this.uiManager.populateAccountSelect(accounts);
        } catch (error) {
            console.error('Lỗi tải danh sách tài khoản:', error);
            this.uiManager.showToast('Không thể tải danh sách tài khoản từ options.json. Kiểm tra file và server.', 'error');
        }
    } async loadDataForAccount() {
        this.uiManager.showLoader(true);
        try {
            const accountSelect = document.getElementById('accountSelect');
            const account = accountSelect.value;

            if (!account) {
                this.uiManager.clearData();
                this.chartManager.destroyCharts();
                // Reset billing cycle display to default

                return;
            }

            const data = await this.dataManager.loadDataForAccount(account);
            this.processAndDisplayData();
            this.uiManager.updateAccountAvatar(account);
        } catch (error) {
            console.error('Lỗi tải dữ liệu:', error);
        } finally {
            this.uiManager.showLoader(false);
        }
    } processAndDisplayData() {
        // Lấy tất cả các năm có sẵn trong dữ liệu
        const availableYears = this.dataManager.getAvailableYears();
        this.uiManager.populateYearSelect(availableYears);

        // Sync currentYear from the actual selected value of yearSelect after population
        const yearSelectEl = document.getElementById('yearSelect');
        if (yearSelectEl) {
            this.currentYear = yearSelectEl.value === 'all' ? null : parseInt(yearSelectEl.value);
        }

        // Cập nhật dropdown tháng (đã lọc theo năm nếu có)
        const uniqueMonths = this.dataManager.getUniqueMonths(this.currentYear);
        this.uiManager.populateMonthSelect(uniqueMonths);

        // Tính toán và hiển thị summary (đã lọc theo năm)
        const summary = this.dataManager.calculateSummary(this.currentYear);
        this.uiManager.updateSummaryNumbers(summary);



        // Tạo summary cards với trend (có thể thay đổi số 4 thành số khác)
        const recentMonths = uniqueMonths.slice(0, 4); // 4 tháng gần nhất
        const trendData = this.dataManager.calculateTrendData(recentMonths);
        this.uiManager.renderSummaryContainer(trendData);        // Tạo biểu đồ monthly (đã lọc theo năm)
        const filteredMonthlyData = this.dataManager.getFilteredMonthlyData(this.currentYear);
        this.chartManager.createMonthlyChart(
            filteredMonthlyData,
            summary.currentPeriod,
            (evt, elements) => this.handleMonthlyChartClick(evt, elements)
        );

        // Tạo biểu đồ daily ban đầu
        const initialMonth = uniqueMonths[0];
        const initialDailyData = this.dataManager.getDataByMonth(initialMonth);
        this.chartManager.createDailyChart(initialDailyData);

        // Hiển thị 5 ngày gần đây trong card tìm kiếm
        const today = new Date();
        const fiveDaysAgo = new Date(today);
        fiveDaysAgo.setDate(today.getDate() - 5);
        const recentDays = this.dataManager.getDataByDateRange(fiveDaysAgo, today);
        this.uiManager.displayRecentDays(recentDays);

        // --- Cấu phần cho Biểu đồ So sánh ---
        const compareAccountSelect = document.getElementById('compareAccountSelect');
        const compareYear1 = document.getElementById('compareYear1');
        const compareYear2 = document.getElementById('compareYear2');

        // Populate compare account selector if needed
        if (compareAccountSelect && compareAccountSelect.options.length <= 2) {
            const accounts = this.dataManager.accounts || [];
            accounts.forEach(acc => {
                if (acc.userevn !== 'all') {
                    const option = new Option(acc.userevn, acc.userevn);
                    compareAccountSelect.add(option);
                }
            });
        }

        if (compareYear1 && compareYear2 && availableYears.length > 0) {
            const val1 = compareYear1.value;
            const val2 = compareYear2.value;
            // isFirstPopulate: compareYear2 chỉ có 1 option duy nhất (option "all" từ HTML)
            // → chưa được populate → không "preserve" val2 === 'all'
            const isFirstPopulate = compareYear2.options.length <= 1;

            compareYear1.innerHTML = '';
            // compareYear2 keeps "Tất cả năm" at top, then individual years
            compareYear2.innerHTML = '<option value="all">Tất cả năm</option>';
            availableYears.forEach(year => {
                compareYear1.add(new Option(`Năm ${year}`, year));
                compareYear2.add(new Option(`Năm ${year}`, year));
            });

            // availableYears is sorted DESCENDING: [2026, 2025, 2024, ...]
            // → compareYear1 (Năm trước) = index 1, compareYear2 (Năm nay) = index 0
            if (val1 && availableYears.includes(parseInt(val1))) {
                compareYear1.value = val1;
            } else {
                compareYear1.value = availableYears.length >= 2 ? availableYears[1] : availableYears[0];
            }

            // Restore year2 selection
            // Chỉ giữ 'all' nếu user đã chọn thủ công (không phải lần đầu load)
            if (!isFirstPopulate && val2 === 'all') {
                compareYear2.value = 'all';
            } else if (val2 && val2 !== 'all' && availableYears.includes(parseInt(val2))) {
                compareYear2.value = val2;
            } else {
                compareYear2.value = availableYears[0]; // Default: năm mới nhất (năm nay)
            }
        }

        this.updateComparisonChart();
    }

    // New helper to update comparison chart independently
    updateComparisonChart() {
        const compareAccountSelect = document.getElementById('compareAccountSelect');
        const compareYear1 = document.getElementById('compareYear1');
        const compareYear2 = document.getElementById('compareYear2');

        const accountMode = compareAccountSelect?.value || 'all';
        const year2Val = compareYear2?.value;
        const year1 = parseInt(compareYear1?.value) || (new Date().getFullYear() - 1);

        // If year2 is 'all', pass 'all' as second year to trigger "all years" mode
        const yearsToCompare = year2Val === 'all' ? ['all'] : [year1, parseInt(year2Val) || new Date().getFullYear()];

        this.chartManager.createComparisonChart(
            this.dataManager.allAccountsData || {},
            yearsToCompare,
            accountMode,
            { type: this.comparisonChartType, showLabels: this.comparisonShowLabels }
        );

        // Update active state of buttons
        this.uiManager.updateChartControlButtons(this.comparisonChartType, this.comparisonShowLabels);
    }

    handleMonthlyChartClick(evt, elements) {
        if (elements && elements.length > 0) {
            const idx = elements[0].index;
            const monthLabel = this.chartManager.monthlyChart.data.labels[idx];

            console.log('📊 Monthly chart clicked:', monthLabel);

            let filteredDailyData;
            let targetMonth;            // Kiểm tra xem có phải "Kỳ này" không
            if (monthLabel.includes('Kỳ này')) {
                console.log('🔍 Clicked on current period');
                // Lấy tháng hiện tại từ uniqueMonths - đã được xử lý đúng ở data.js
                const uniqueMonths = this.dataManager.getUniqueMonths();
                targetMonth = uniqueMonths[0]; // "Kỳ này" thường ở index 0

                console.log('🔍 Target month for current period:', targetMonth);
                filteredDailyData = this.dataManager.getDataByMonth(targetMonth);
                console.log('🔍 Current period data:', filteredDailyData?.length, 'days');
            } else {
                // Lấy tháng từ label ("Tháng 05-2025" hoặc "T05-2025")
                const monthMatch = monthLabel.match(/(?:Tháng|T)\s*[-]?\s*(\d{1,2})/i);
                if (monthMatch) {
                    const monthNum = monthMatch[1].padStart(2, '0');
                    targetMonth = `${monthNum}-${this.currentYear}`;
                    filteredDailyData = this.dataManager.getDataByMonth(targetMonth);
                    console.log('🔍 Monthly data:', filteredDailyData?.length, 'days');
                }
            }

            if (filteredDailyData) {
                this.chartManager.createDailyChart(filteredDailyData);

                // Scroll tới daily chart
                document.getElementById('dailyChart').scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            } else {
                console.error('❌ No data found for clicked period:', monthLabel);
            }
        }
    }

    setupEventListeners() {
        // Resize listener
        window.addEventListener('resize', () => {
            if (this.dataManager.currentAccount) {
                clearTimeout(this.resizeTimeout);
                this.resizeTimeout = setTimeout(() => {
                    console.log('Window resized, refreshing charts...');
                    this.processAndDisplayData();
                }, 250);
            }
        });

        // Account select change
        const accountSelect = document.getElementById('accountSelect');
        if (accountSelect) {
            accountSelect.addEventListener('change', () => {
                this.loadDataForAccount();
                this.saveUIState(); // Save state on account change
            });
        }

        // Comparison Selects
        const compareAccountSelect = document.getElementById('compareAccountSelect');
        const compareYear1 = document.getElementById('compareYear1');
        const compareYear2 = document.getElementById('compareYear2');

        if (compareAccountSelect) {
            compareAccountSelect.addEventListener('change', () => this.updateComparisonChart());
        }
        if (compareYear1) {
            compareYear1.addEventListener('change', () => this.updateComparisonChart());
        }
        if (compareYear2) {
            compareYear2.addEventListener('change', () => this.updateComparisonChart());
        }

        // Comparison Chart Controls
        const barBtn = document.getElementById('compareBarBtn');
        const lineBtn = document.getElementById('compareLineBtn');
        const labelBtn = document.getElementById('compareLabelBtn');

        if (barBtn) {
            barBtn.addEventListener('click', () => {
                this.comparisonChartType = 'bar';
                localStorage.setItem('comparisonChartType', 'bar');
                this.updateComparisonChart();
            });
        }
        if (lineBtn) {
            lineBtn.addEventListener('click', () => {
                this.comparisonChartType = 'line';
                localStorage.setItem('comparisonChartType', 'line');
                this.updateComparisonChart();
            });
        }
        if (labelBtn) {
            labelBtn.addEventListener('click', () => {
                this.comparisonShowLabels = !this.comparisonShowLabels;
                localStorage.setItem('comparisonShowLabels', this.comparisonShowLabels);
                this.updateComparisonChart();
            });
        }


        // Month select change
        const monthSelect = document.getElementById('monthSelect');
        if (monthSelect) {
            monthSelect.addEventListener('change', (e) => {
                const filteredDailyData = this.dataManager.getDataByMonth(e.target.value);
                this.chartManager.createDailyChart(filteredDailyData);
                this.saveUIState(); // Save state on month change
            });
        }

        // Year select change
        const yearSelect = document.getElementById('yearSelect');
        if (yearSelect) {
            yearSelect.addEventListener('change', (e) => {
                const selectedYear = e.target.value;
                this.currentYear = selectedYear === 'all' ? null : parseInt(selectedYear);
                console.log('📅 Year changed to:', this.currentYear || 'all');
                this.processAndDisplayData();
                this.saveUIState(); // Save state on year change
            });
        }        // Search functionality
        const searchBtn = document.getElementById('searchBtn');
        if (searchBtn) {
            searchBtn.addEventListener('click', () => this.handleSearch());
        }        // Date inputs
        const startDate = document.getElementById('startDate');
        const endDate = document.getElementById('endDate');
        if (startDate && endDate) {
            // Set default dates
            const today = new Date();
            const fiveDaysAgo = new Date(today);
            fiveDaysAgo.setDate(today.getDate() - 5);

            endDate.value = today.toISOString().split('T')[0];
            startDate.value = fiveDaysAgo.toISOString().split('T')[0];

            // Add event listeners to save state on change
            startDate.addEventListener('change', () => this.saveUIState());
            endDate.addEventListener('change', () => this.saveUIState());

            // Hiển thị dữ liệu 5 ngày gần đây khi trang được tải
            setTimeout(() => {
                if (this.dataManager && this.dataManager.dailyData && this.dataManager.dailyData.length > 0) {
                    // Lấy dữ liệu 5 ngày gần đây
                    const filteredData = this.dataManager.getDataByDateRange(fiveDaysAgo, today);

                    if (filteredData.length > 0) {
                        // Cập nhật biểu đồ
                        this.chartManager.createDailyChart(filteredData);

                        // Hiển thị dữ liệu trong card tìm kiếm
                        this.uiManager.displayRecentDays(filteredData);
                    }
                }
            }, 1000); // Delay 1 second to ensure data is loaded
        }

        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => this.handleFilterClick(btn));
        });        // Detail table toggle
        const toggleDetailTable = document.getElementById('toggleDetailTable');
        if (toggleDetailTable) {
            toggleDetailTable.addEventListener('click', () => this.toggleDetailTable());
        }

        // Modal event listeners - delay để đảm bảo DOM đã load
        setTimeout(() => {
            this.setupModalEventListeners();
        }, 100);

        // Summary month cards click handling
        this.setupSummaryCardsClickHandler();        // Trang được tải sẽ tự động hiển thị 5 ngày gần nhất (đã xử lý trong setup date inputs)
    } handleSearch() {
        const searchBtn = document.getElementById('searchBtn');
        const startDateInput = document.getElementById('startDate');
        const endDateInput = document.getElementById('endDate');

        // Add loading effect to button
        if (searchBtn) {
            searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang xử lý...';
            searchBtn.disabled = true;
        }

        const startDate = new Date(startDateInput.value);
        const endDate = new Date(endDateInput.value);

        if (isNaN(startDate) || isNaN(endDate)) {
            this.uiManager.showToast('Vui lòng chọn ngày bắt đầu và ngày kết thúc hợp lệ!', 'error');
            if (searchBtn) {
                searchBtn.innerHTML = '<i class="fas fa-search"></i> Tìm kiếm';
                searchBtn.disabled = false;
            }
            return;
        }

        if (startDate > endDate) {
            this.uiManager.showToast('Ngày bắt đầu không thể lớn hơn ngày kết thúc!', 'error');
            if (searchBtn) {
                searchBtn.innerHTML = '<i class="fas fa-search"></i> Tìm kiếm';
                searchBtn.disabled = false;
            }
            return;
        }

        // Lọc dữ liệu
        const filteredData = this.dataManager.getDataByDateRange(startDate, endDate);

        if (filteredData.length === 0) {
            this.uiManager.showToast('Không có dữ liệu trong khoảng thời gian đã chọn', 'error');
            if (searchBtn) {
                searchBtn.innerHTML = '<i class="fas fa-search"></i> Tìm kiếm';
                searchBtn.disabled = false;
            }
            return;
        }

        // Tính tổng cho khoảng thời gian
        const totalConsumptionInRange = filteredData.reduce((sum, day) =>
            sum + day["Điện tiêu thụ (kWh)"], 0
        );

        // Cập nhật biểu đồ
        this.chartManager.createDailyChart(filteredData);

        // Mở popup chi tiết tiêu thụ điện - chỉ khi người dùng bấm tìm kiếm
        // Mở modal khi đây là hành động chủ động từ người dùng, không phải tự động lúc tải trang
        if (searchBtn) {
            this.openDetailModal(true);

            // Hiển thị dữ liệu trong bảng chi tiết
            this.renderDetailTable(filteredData);
        }

        // Hiển thị thông báo thành công
        this.uiManager.showToast(`Đã tìm thấy ${filteredData.length} ngày với tổng tiêu thụ ${totalConsumptionInRange.toFixed(2)} kWh`, 'success');
        // Hiển thị lại dữ liệu gần đây sau khi tìm kiếm
        const today = new Date();
        const fiveDaysAgo = new Date(today);
        fiveDaysAgo.setDate(today.getDate() - 5);
        const recentDays = this.dataManager.getDataByDateRange(fiveDaysAgo, today);
        this.uiManager.displayRecentDays(recentDays);

        // Reset button state
        if (searchBtn) {
            searchBtn.innerHTML = '<i class="fas fa-search"></i> Tìm kiếm';
            searchBtn.disabled = false;
        }
    }

    handleFilterClick(btn) {
        const days = parseInt(btn.dataset.range);
        const sorted = [...this.dataManager.dailyData].sort((a, b) =>
            new Date(b.Ngày.split('-').reverse().join('-')) -
            new Date(a.Ngày.split('-').reverse().join('-'))
        );
        const filtered = sorted.filter(d => d["Điện tiêu thụ (kWh)"] > 0)
            .slice(0, days)
            .reverse();

        this.chartManager.createDailyChart(filtered);
        this.renderDetailTable(filtered);
    } toggleDetailTable() {
        // Mở popup modal thay vì toggle bảng trong card
        this.openDetailModal(false);
    } openDetailModal(fromSearch = true) {
        const modal = document.getElementById('detailModal');
        if (!modal) {
            console.error('Modal element not found');
            return;
        }

        // Update modal title based on context
        const modalTitle = modal.querySelector('.modal-title');
        if (modalTitle) {
            if (fromSearch) {
                const startDate = document.getElementById('startDate')?.value;
                const endDate = document.getElementById('endDate')?.value;
                if (startDate && endDate) {
                    const formattedStart = new Date(startDate).toLocaleDateString('vi-VN');
                    const formattedEnd = new Date(endDate).toLocaleDateString('vi-VN');
                    modalTitle.innerHTML = `Chi Tiết Tiêu Thụ Điện (${formattedStart} - ${formattedEnd})`;
                } else {
                    modalTitle.innerHTML = 'Chi Tiết Tiêu Thụ Điện';
                }
            } else {
                modalTitle.innerHTML = 'Chi Tiết Tiêu Thụ Điện';
            }
        }

        modal.classList.add('show');
        document.body.style.overflow = 'hidden'; // Prevent scrolling behind modal

        // Render lại bảng với dữ liệu hiện tại
        const currentData = this.getCurrentDisplayData();
        this.renderDetailTable(currentData);
    }

    closeDetailModal() {
        const modal = document.getElementById('detailModal');
        if (!modal) {
            console.error('Modal element not found');
            return;
        }

        modal.classList.remove('show');
        document.body.style.overflow = ''; // Restore scrolling
    } getCurrentDisplayData() {
        // Lấy dữ liệu hiện tại đang hiển thị trên daily chart
        if (this.chartManager && this.chartManager.dailyChart && this.chartManager.dailyChart.data) {
            // Lấy từ daily chart data đang hiển thị
            const chartData = this.chartManager.dailyChart.data;
            const labels = chartData.labels || [];
            const dataPoints = chartData.datasets[0]?.data || [];

            console.log('📊 Getting current display data from chart:', labels.length, 'days');

            // Tạo array data từ chart hiện tại
            const currentData = labels.map((label, index) => {
                return {
                    'Ngày': label,
                    'Điện tiêu thụ (kWh)': dataPoints[index] || 0,
                    'Tiền điện': null // Sẽ tính sau nếu cần
                };
            });

            return currentData;
        }

        // Fallback: Lấy từ month select như cũ
        const selectedMonth = document.getElementById('monthSelect')?.value;
        if (!selectedMonth || !this.dataManager) {
            return [];
        }
        console.log('📊 Fallback: Getting data by month select:', selectedMonth);
        return this.dataManager.getDataByMonth(selectedMonth);
    } renderDetailTable(data) {
        const tbody = document.querySelector('#detailTable tbody');
        const statsContainer = document.getElementById('tableStats');
        if (!tbody) return;

        tbody.innerHTML = '';
        if (statsContainer) statsContainer.innerHTML = '';
        if (!data || data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-gray-400">Không có dữ liệu</td></tr>';
            if (statsContainer) {
                statsContainer.innerHTML = '<div class="text-center text-gray-400">Không có dữ liệu để thống kê</div>';
            }
            return;
        }

        // Lọc dữ liệu chỉ hiển thị ngày có tiêu thụ > 0
        const validData = data.filter(d => d["Điện tiêu thụ (kWh)"] > 0);
        if (validData.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-gray-400">Không có dữ liệu tiêu thụ</td></tr>';
            if (statsContainer) {
                statsContainer.innerHTML = '<div class="text-center text-gray-400">Không có dữ liệu tiêu thụ để thống kê</div>';
            }
            return;
        }

        // Sắp xếp dữ liệu theo thứ tự thời gian để tính bậc thang tích lũy
        const sortedData = [...validData].sort((a, b) => {
            const dateA = new Date(a.Ngày.split('-').reverse().join('-'));
            const dateB = new Date(b.Ngày.split('-').reverse().join('-'));
            return dateA - dateB;
        });

        // Tính toán tiền điện theo bậc thang tích lũy
        const dataWithCosts = this.calculateDailyCostWithTiers(sortedData);

        // Highlight max/min
        const vals = dataWithCosts.map(d => d.kwh);
        const max = Math.max(...vals);
        const min = Math.min(...vals);
        const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
        const totalKwh = vals.reduce((a, b) => a + b, 0);
        const totalCost = dataWithCosts.reduce((sum, d) => sum + d.dailyCost, 0);

        // Hiển thị dữ liệu trong bảng
        dataWithCosts.forEach(dayData => {
            const { date, kwh, dailyCost, avgTierPrice, isMax, isMin } = dayData;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="px-2 py-1">${date}</td>
                <td class="px-2 py-1 ${isMax ? 'highlight-max' : ''} ${isMin ? 'highlight-min' : ''}">${kwh.toFixed(2)}</td>
                <td class="px-2 py-1">${dailyCost.toLocaleString('vi-VN')} VNĐ</td>
                <td class="px-2 py-1">${avgTierPrice.toFixed(0)} VNĐ/kWh</td>
            `;
            tbody.appendChild(tr);
        });

        // Hiển thị thống kê ở phần cố định
        if (statsContainer) {
            const maxData = dataWithCosts.find(d => d.kwh === max);
            const minData = dataWithCosts.find(d => d.kwh === min);

            statsContainer.innerHTML = `
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <!-- Thống kê tổng quan -->
                    <div class="bg-blue-900 bg-opacity-50 p-3 rounded-lg">
                        <h4 class="font-bold text-blue-300 mb-2 flex items-center">
                            <i class="fas fa-chart-bar mr-2"></i>📊 Tổng quan
                        </h4>
                        <div class="space-y-1 text-xs">
                            <div><strong>Tổng:</strong> ${totalKwh.toFixed(2)} kWh</div>
                            <div><strong>TB:</strong> ${avg.toFixed(2)} kWh/ngày</div>
                            <div><strong>Tiền:</strong> ${totalCost.toLocaleString('vi-VN')} VNĐ</div>
                            <div><strong>TB:</strong> ${(totalCost / dataWithCosts.length).toFixed(0)} VNĐ/ngày</div>
                            <div><strong>Số ngày:</strong> ${dataWithCosts.length} ngày</div>
                        </div>
                    </div>
                    
                    <!-- Max -->
                    <div class="bg-green-900 bg-opacity-50 p-3 rounded-lg">
                        <h4 class="font-bold text-green-300 mb-2 flex items-center">
                            <i class="fas fa-arrow-up mr-2"></i>📈 Cao nhất
                        </h4>
                        <div class="space-y-1 text-xs">
                            <div><strong>Ngày:</strong> ${maxData ? maxData.date : '-'}</div>
                            <div><strong>Tiêu thụ:</strong> <span class="highlight-max">${max.toFixed(2)} kWh</span></div>
                            <div><strong>Tiền:</strong> ${maxData ? maxData.dailyCost.toLocaleString('vi-VN') + ' VNĐ' : '-'}</div>
                            <div><strong>Giá:</strong> ${maxData ? maxData.avgTierPrice.toFixed(0) + ' VNĐ/kWh' : '-'}</div>
                        </div>
                    </div>
                    
                    <!-- Min -->
                    <div class="bg-red-900 bg-opacity-50 p-3 rounded-lg">
                        <h4 class="font-bold text-red-300 mb-2 flex items-center">
                            <i class="fas fa-arrow-down mr-2"></i>📉 Thấp nhất
                        </h4>
                        <div class="space-y-1 text-xs">
                            <div><strong>Ngày:</strong> ${minData ? minData.date : '-'}</div>
                            <div><strong>Tiêu thụ:</strong> <span class="highlight-min">${min.toFixed(2)} kWh</span></div>
                            <div><strong>Tiền:</strong> ${minData ? minData.dailyCost.toLocaleString('vi-VN') + ' VNĐ' : '-'}</div>
                            <div><strong>Giá:</strong> ${minData ? minData.avgTierPrice.toFixed(0) + ' VNĐ/kWh' : '-'}</div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    // Hàm tính toán tiền điện theo bậc thang tích lũy đúng cách
    calculateDailyCostWithTiers(sortedData) {
        const tiers = [
            { limit: 50, price: 1984 },
            { limit: 50, price: 2050 },
            { limit: 100, price: 2380 },
            { limit: 100, price: 2998 },
            { limit: 100, price: 3350 },
            { limit: Infinity, price: 3460 }
        ];

        let cumulativeKwh = 0;
        let previousTotalCost = 0;

        // Tính max/min để highlight
        const vals = sortedData.map(d => d["Điện tiêu thụ (kWh)"]);
        const max = Math.max(...vals);
        const min = Math.min(...vals);

        return sortedData.map(day => {
            const kwh = day["Điện tiêu thụ (kWh)"];
            cumulativeKwh += kwh;

            // Tính tổng tiền từ đầu chu kỳ đến ngày hiện tại
            const currentTotalCost = this.calculateCostFromTiers(cumulativeKwh, tiers);

            // Tiền điện của ngày hiện tại = tổng tiền hiện tại - tổng tiền ngày trước
            const dailyCost = currentTotalCost - previousTotalCost;

            // Tính đơn giá trung bình cho ngày này
            const avgTierPrice = kwh > 0 ? dailyCost / kwh : 0;

            previousTotalCost = currentTotalCost;

            return {
                date: day.Ngày,
                kwh: kwh,
                dailyCost: Math.round(dailyCost),
                avgTierPrice: avgTierPrice,
                cumulativeKwh: cumulativeKwh,
                isMax: kwh === max,
                isMin: kwh === min
            };
        });
    }

    // Hàm tính tổng tiền điện từ các bậc thang (với thuế)
    calculateCostFromTiers(totalKwh, tiers) {
        let remainingKwh = totalKwh;
        let totalCost = 0;
        let usedSoFar = 0;

        for (let i = 0; i < tiers.length; i++) {
            const tier = tiers[i];
            const tierLimit = i < tiers.length - 1 ? tier.limit : Infinity;
            const kwhInTier = Math.min(remainingKwh, tierLimit);

            if (kwhInTier > 0) {
                const cost = kwhInTier * tier.price;
                totalCost += cost;

                remainingKwh -= kwhInTier;
                usedSoFar += kwhInTier;

                if (remainingKwh <= 0) break;
            }
        }

        // Thêm thuế VAT 8%
        const tax = totalCost * 0.08;
        return totalCost + tax;
    }

    // Setup event listeners cho summary month cards
    setupSummaryCardsClickHandler() {
        // Sử dụng event delegation để handle click cho các cards động
        const summaryContainer = document.getElementById('summaryContainer');
        if (summaryContainer) {
            summaryContainer.addEventListener('click', (e) => {
                // Tìm summary card được click
                const summaryCard = e.target.closest('.summary-month-card');
                if (summaryCard) {
                    this.handleSummaryCardClick(summaryCard);
                }
            });
        }
    }    // Xử lý click vào summary month card
    handleSummaryCardClick(card) {
        console.log('🔍 Summary card clicked:', card);

        const cardId = card.id;
        const cardIndex = cardId.replace('summary-month-', '');
        console.log('📌 Card ID:', cardId, 'Index:', cardIndex);

        // Lấy dữ liệu tháng tương ứng
        const uniqueMonths = this.dataManager.getUniqueMonths();
        const targetMonth = uniqueMonths[parseInt(cardIndex)];
        console.log('🎯 Unique months:', uniqueMonths);
        console.log('🎯 Target month:', targetMonth);

        if (targetMonth) {
            // Kiểm tra xem có phải "Kỳ này" không
            const cardTitle = card.querySelector('h4');
            const isCurrentPeriod = cardTitle && cardTitle.textContent.includes('Kỳ này');
            console.log('🔍 Card title:', cardTitle?.textContent);
            console.log('🔍 Is current period:', isCurrentPeriod);
            let filteredDailyData; if (isCurrentPeriod) {
                // Lấy dữ liệu theo chu kỳ thanh toán hiện tại - logic đã được xử lý ở data.js
                console.log('🔍 Current period - target month:', targetMonth);
                filteredDailyData = this.dataManager.getDataByMonth(targetMonth);
                console.log('🔍 Current period data:', filteredDailyData?.length, 'days');
            } else {
                // Lấy dữ liệu theo tháng thông thường
                filteredDailyData = this.dataManager.getDataByMonth(targetMonth);
                console.log('🔍 Monthly data:', filteredDailyData?.length, 'days');
            }

            // Cập nhật daily chart
            console.log('📊 Updating daily chart with data:', filteredDailyData?.length, 'days');
            this.chartManager.createDailyChart(filteredDailyData);

            // Scroll tới daily chart
            const dailyChart = document.getElementById('dailyChart');
            if (dailyChart) {
                dailyChart.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        } else {
            console.error('❌ Target month not found for index:', cardIndex);
        }
    } setupModalEventListeners() {
        const modal = document.getElementById('detailModal');
        const closeBtn = document.getElementById('modalCloseBtn');

        if (!modal) {
            console.error('Modal element not found in setupModalEventListeners');
            return;
        }

        // Close button event listener
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this.closeDetailModal();
            });
        }

        // Đóng modal khi click outside
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                this.closeDetailModal();
            }
        });

        // Đóng modal khi nhấn ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('show')) {
                this.closeDetailModal();
            }
        });
    }

    // Save current UI state to localStorage
    saveUIState() {
        const accountSelect = document.getElementById('accountSelect');
        const monthSelect = document.getElementById('monthSelect');
        const yearSelect = document.getElementById('yearSelect');
        const startDate = document.getElementById('startDate');
        const endDate = document.getElementById('endDate');

        const state = {
            selectedAccount: accountSelect?.value || '',
            selectedMonth: monthSelect?.value || '',
            selectedYear: yearSelect?.value || 'all',
            startDate: startDate?.value || '',
            endDate: endDate?.value || ''
        };

        localStorage.setItem('uiState', JSON.stringify(state));
        console.log('🔄 UI State saved:', state);
    }

    // Restore UI state from localStorage
    restoreUIState() {
        try {
            const savedState = localStorage.getItem('uiState');
            if (!savedState) return;

            const state = JSON.parse(savedState);
            console.log('🔄 Restoring UI State:', state);

            // Restore account selection
            const accountSelect = document.getElementById('accountSelect');
            if (accountSelect && state.selectedAccount) {
                accountSelect.value = state.selectedAccount;
            }

            // Restore year selection - only restore non-'all' values from localStorage
            // because 'all' is no longer the desired default (we default to current year)
            const yearSelect = document.getElementById('yearSelect');
            if (yearSelect && state.selectedYear && state.selectedYear !== 'all') {
                yearSelect.value = state.selectedYear;
                this.currentYear = parseInt(state.selectedYear);
            }
            // If state.selectedYear is 'all', let populateYearSelect pick the default (current year)

            // Restore month selection
            const monthSelect = document.getElementById('monthSelect');
            if (monthSelect && state.selectedMonth) {
                monthSelect.value = state.selectedMonth;
            }

            // Restore date inputs
            const startDate = document.getElementById('startDate');
            const endDate = document.getElementById('endDate');
            if (startDate && state.startDate) {
                startDate.value = state.startDate;
            }
            if (endDate && state.endDate) {
                endDate.value = state.endDate;
            }

        } catch (error) {
            console.error('❌ Error restoring UI state:', error);
        }
    }
}

// Khởi tạo ứng dụng khi DOM ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new ElectricityApp();
});

// Export cho global access
window.ElectricityApp = ElectricityApp;
