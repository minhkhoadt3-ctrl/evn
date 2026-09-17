// Data Management Module
// Get the current Home Assistant access token for API requests.
function getHAAuthHeaders() {
    let token = null;
    try {
        const ha = window.parent?.document?.querySelector("home-assistant");
        token = ha?.hass?.auth?.data?.access_token || null;
    } catch (error) {
        // Fall back to localStorage below.
    }
    if (!token) {
        try {
            const raw = window.localStorage.getItem("hassTokens");
            if (raw) {
                token = JSON.parse(raw)?.access_token || null;
            }
        } catch (error) {
            // Ignore unavailable or malformed token storage.
        }
    }
    return token ? { Authorization: `Bearer ${token}` } : {};
}

async function haFetch(url, options = {}) {
    return fetch(url, {
        ...options,
        headers: { ...getHAAuthHeaders(), ...(options.headers || {}) }
    });
}

class DataManager {
    constructor() {
        this.monthlyData = null;
        this.dailyData = null;
        this.currentAccount = null;
        this.currentYear = new Date().getFullYear();
        this.currentPeriodFromSensor = null;

        // CẤM: Không dùng cấu hình cũ trong localStorage để tránh bị dính ngày 15 demo
        localStorage.removeItem('billingCycles');

        // Cấu hình chu kỳ thanh toán theo tài khoản
        this.billingCycles = {
            // Default: đầu tháng đến cuối tháng
            default: { startDay: 1, type: 'calendar' }
        };

        // Cache for all accounts data (used for comparison chart)
        this.allAccountsData = {};
        this.accounts = [];
    }

    // Load danh sách accounts từ options.json
    async loadAccounts() {
        try {
            const baseUrl = this.getBaseUrl();
            const response = await haFetch(baseUrl + '/api/npc/options');

            if (!response.ok) {
                throw new Error('Không thể tải danh sách tài khoản từ API');
            }

            const options = await response.json();
            const accounts = JSON.parse(options.accounts_json);

            this.accounts = accounts;
            // Cập nhật billing cycle từ config API (luôn ghi đè)
            accounts.forEach(acc => {
                const startDay = parseInt(acc.ngaydauky) || 1;
                this.billingCycles[acc.customer_id] = {
                    startDay: startDay,
                    type: startDay > 1 ? 'cycle' : 'calendar'
                };
                console.log(`📡 API Config for ${acc.customer_id}: startDay=${startDay}, type=${this.billingCycles[acc.customer_id].type}`);
            });

            // Lưu danh sách gốc để gộp dữ liệu sau này
            this.allRealAccounts = accounts;

            // Thêm tùy chọn "Tất cả công tơ" nếu có nhiều hơn 1 tài khoản
            if (accounts.length > 1) {
                const combinedAccounts = [
                    {
                        userevn: "all",
                        id: "all",
                        name: "Tất cả công tơ",
                        customer_id: "all",
                        ngaydauky: 1
                    },
                    ...accounts
                ];
                return combinedAccounts;
            }

            return accounts;
        } catch (error) {
            console.error('Lỗi tải danh sách tài khoản:', error);
            throw error;
        }
    }

    // Load dữ liệu cho một tài khoản cụ thể
    async loadDataForAccount(account) {
        if (account === "all") {
            return await this.loadAllAccountsData();
        }
        try {
            const baseUrl = this.getBaseUrl();

            // Load monthly data
            const monthlyResponse = await haFetch(`${baseUrl}/api/npc/monthly/${account}`);
            if (!monthlyResponse.ok) {
                throw new Error(`Không thể tải dữ liệu hóa đơn cho ${account}`);
            }
            this.monthlyData = await monthlyResponse.json();
            console.log('📊 Monthly data loaded:', this.monthlyData);

            // Load daily data
            const dailyResponse = await haFetch(`${baseUrl}/api/npc/daily/${account}`);
            if (!dailyResponse.ok) {
                throw new Error(`Không thể tải dữ liệu tiêu thụ cho ${account}`);
            }
            this.dailyData = await dailyResponse.json();
            console.log('📅 Daily data loaded:', this.dailyData?.length, 'records');

            // Load current period data from sensors
            try {
                const currentResponse = await haFetch(`${baseUrl}/api/npc/current/${account}`);
                if (currentResponse.ok) {
                    this.currentPeriodFromSensor = await currentResponse.json();
                    console.log('⚡ Current period from sensor:', this.currentPeriodFromSensor);
                }
            } catch (err) {
                console.warn('Could not load current period from sensor:', err);
                this.currentPeriodFromSensor = null;
            }

            this.currentAccount = account;
            this.allAccountsData[account] = {
                monthly: this.monthlyData,
                daily: this.dailyData
            };
            this.processData();
            console.log('✅ Data processed. Monthly:', this.monthlyData?.SanLuong?.length, 'months, Daily:', this.dailyData?.length, 'days');

            return {
                monthlyData: this.monthlyData,
                dailyData: this.dailyData,
                currentPeriodFromSensor: this.currentPeriodFromSensor
            };
        } catch (error) {
            console.error('Lỗi tải dữ liệu:', error);
            throw error;
        }
    }

    // Load và gộp dữ liệu từ tất cả tài khoản
    async loadAllAccountsData() {
        try {
            const baseUrl = this.getBaseUrl();
            const accounts = this.allRealAccounts || [];

            if (accounts.length === 0) {
                throw new Error("Không tìm thấy danh sách tài khoản để gộp");
            }

            console.log('🔄 Aggregating data for all accounts:', accounts.map(a => a.customer_id));

            let aggregatedMonthly = { SanLuong: [], TienDien: [] };
            let aggregatedDaily = [];
            let aggregatedCurrent = { tieu_thu_ky_nay: 0, tien_dien_ky_nay: 0 };

            // Fetch data song song cho tất cả các tài khoản
            const promises = accounts.map(async (acc) => {
                const id = acc.customer_id;
                try {
                    const [monthlyRes, dailyRes, currentRes] = await Promise.all([
                        haFetch(`${baseUrl}/api/npc/monthly/${id}`),
                        haFetch(`${baseUrl}/api/npc/daily/${id}`),
                        haFetch(`${baseUrl}/api/npc/current/${id}`)
                    ]);

                    return {
                        monthly: monthlyRes.ok ? await monthlyRes.json() : { SanLuong: [], TienDien: [] },
                        daily: dailyRes.ok ? await dailyRes.json() : [],
                        current: currentRes.ok ? await currentRes.json() : null
                    };
                } catch (e) {
                    console.warn(`Could not load data for account ${id}:`, e);
                    return { monthly: { SanLuong: [], TienDien: [] }, daily: [], current: null };
                }
            });

            const results = await Promise.all(promises);

            // Store each account's data in the cache
            accounts.forEach((acc, i) => {
                this.allAccountsData[acc.customer_id] = {
                    monthly: results[i].monthly,
                    daily: results[i].daily
                };
            });

            results.forEach(res => {
                // Gộp dữ liệu tháng
                if (res.monthly && res.monthly.SanLuong) {
                    res.monthly.SanLuong.forEach(item => {
                        let existing = aggregatedMonthly.SanLuong.find(i => i.Tháng === item.Tháng && i.Năm === item.Năm);
                        const val = typeof item["Điện tiêu thụ (KWh)"] === 'number' ? item["Điện tiêu thụ (KWh)"] : parseFloat(item["Điện tiêu thụ (KWh)"]) || 0;
                        if (existing) {
                            existing["Điện tiêu thụ (KWh)"] += val;
                        } else {
                            aggregatedMonthly.SanLuong.push({ ...item, "Điện tiêu thụ (KWh)": val });
                        }
                    });
                }
                if (res.monthly && res.monthly.TienDien) {
                    res.monthly.TienDien.forEach(item => {
                        let existing = aggregatedMonthly.TienDien.find(i => i.Tháng === item.Tháng && i.Năm === item.Năm);
                        const val = typeof item["Tiền Điện"] === 'number' ? item["Tiền Điện"] : parseFloat(item["Tiền Điện"]) || 0;
                        if (existing) {
                            existing["Tiền Điện"] += val;
                        } else {
                            aggregatedMonthly.TienDien.push({ ...item, "Tiền Điện": val });
                        }
                    });
                }

                // Gộp dữ liệu ngày
                if (res.daily && Array.isArray(res.daily)) {
                    res.daily.forEach(item => {
                        let existing = aggregatedDaily.find(i => i.Ngày === item.Ngày);
                        // Chuẩn hóa giá trị trước khi cộng
                        let consumption = item["Điện tiêu thụ (kWh)"];
                        if (typeof consumption === 'string') {
                            consumption = parseFloat(consumption.replace(',', '.')) || 0;
                        } else {
                            consumption = parseFloat(consumption) || 0;
                        }

                        let cost = item["Tiền điện (VND)"];
                        if (typeof cost === 'string') {
                            cost = parseFloat(cost.replace(',', '.')) || 0;
                        } else {
                            cost = parseFloat(cost) || 0;
                        }

                        if (existing) {
                            existing["Điện tiêu thụ (kWh)"] += consumption;
                            existing["Tiền điện (VND)"] += cost;
                        } else {
                            aggregatedDaily.push({
                                ...item,
                                "Điện tiêu thụ (kWh)": consumption,
                                "Tiền điện (VND)": cost
                            });
                        }
                    });
                }

                // Gộp dữ liệu kỳ hiện tại
                if (res.current) {
                    aggregatedCurrent.tieu_thu_ky_nay += res.current.tieu_thu_ky_nay || 0;
                    aggregatedCurrent.tien_dien_ky_nay += res.current.tien_dien_ky_nay || 0;
                }
            });

            this.monthlyData = aggregatedMonthly;
            this.dailyData = aggregatedDaily;
            this.currentPeriodFromSensor = aggregatedCurrent;
            this.currentAccount = "all";
            this.processData();

            console.log('✅ Aggregated data ready. Monthly:', this.monthlyData.SanLuong.length, 'Daily:', this.dailyData.length);

            return {
                monthlyData: this.monthlyData,
                dailyData: this.dailyData,
                currentPeriodFromSensor: this.currentPeriodFromSensor
            };
        } catch (error) {
            console.error('Lỗi gộp dữ liệu:', error);
            throw error;
        }
    }

    // Xử lý và chuẩn hóa dữ liệu
    processData() {
        // Xử lý daily data
        if (this.dailyData && Array.isArray(this.dailyData)) {
            this.dailyData.forEach(day => {
                if (day["Điện tiêu thụ (kWh)"] !== "Không có dữ liệu") {
                    const value = day["Điện tiêu thụ (kWh)"];
                    if (typeof value === 'string') {
                        day["Điện tiêu thụ (kWh)"] = parseFloat(value.replace(',', '.')) || 0;
                    } else {
                        day["Điện tiêu thụ (kWh)"] = parseFloat(value) || 0;
                    }
                } else {
                    day["Điện tiêu thụ (kWh)"] = 0;
                }
            });

            // Sắp xếp dữ liệu theo thứ tự thời gian
            this.dailyData.sort((a, b) =>
                new Date(a.Ngày.split('-').reverse().join('-')) -
                new Date(b.Ngày.split('-').reverse().join('-'))
            );
        } else {
            this.dailyData = [];
        }

        // Sắp xếp monthly data
        if (this.monthlyData && this.monthlyData.SanLuong && Array.isArray(this.monthlyData.SanLuong)) {
            this.monthlyData.SanLuong = this.monthlyData.SanLuong.filter(item => {
                const year = this.normalizeYearValue(item.Năm);
                const month = parseInt(item.Tháng, 10);
                return year !== null && !Number.isNaN(month);
            }).sort((a, b) => a.Tháng - b.Tháng);
        } else if (this.monthlyData) {
            this.monthlyData.SanLuong = [];
        }

        if (this.monthlyData && this.monthlyData.TienDien && Array.isArray(this.monthlyData.TienDien)) {
            this.monthlyData.TienDien = this.monthlyData.TienDien.filter(item => {
                const year = this.normalizeYearValue(item.Năm);
                const month = parseInt(item.Tháng, 10);
                return year !== null && !Number.isNaN(month);
            }).sort((a, b) => a.Tháng - b.Tháng);
        } else if (this.monthlyData) {
            this.monthlyData.TienDien = [];
        }

        // Đảm bảo monthlyData có structure đúng
        if (!this.monthlyData) {
            this.monthlyData = { SanLuong: [], TienDien: [] };
        }
    }    // Lấy dữ liệu theo tháng (hỗ trợ chu kỳ thanh toán)
    getDataByMonth(monthYear) {
        const billingCycle = this.getBillingCycle();

        if (billingCycle.type === 'calendar') {
            // Chu kỳ theo tháng dương lịch (cũ)
            return this.dailyData.filter(day =>
                day.Ngày && day.Ngày.slice(3, 10) === monthYear
            );
        } else if (billingCycle.type === 'cycle' && billingCycle.startDay === 1) {
            // Chu kỳ được cấu hình thủ công từ ngày 1 - xử lý như tháng dương lịch
            return this.dailyData.filter(day =>
                day.Ngày && day.Ngày.slice(3, 10) === monthYear
            );
        } else {
            // Chu kỳ thanh toán tùy chỉnh
            return this.getDataByBillingPeriod(monthYear, billingCycle.startDay);
        }
    }    // Lấy cấu hình chu kỳ thanh toán cho tài khoản hiện tại
    getBillingCycle() {
        const cycle = this.billingCycles[this.currentAccount] || this.billingCycles.default;
        console.log('🔍 getBillingCycle:', { currentAccount: this.currentAccount, cycle });
        return cycle;
    }

    // Tính ngày đầu kỳ, cuối kỳ theo logic đúng từ NPC
    tinhngaydauky(ngaydauky, today = null) {
        if (today === null) {
            today = new Date();
        }

        const day = today.getDate();
        const month = today.getMonth(); // 0-based (0 = January)
        const year = today.getFullYear();

        let start;

        if (ngaydauky === 1) {
            // Chu kỳ theo tháng dương lịch
            start = new Date(year, month, 1);
        } else {
            // Chu kỳ tùy chỉnh
            if (day < ngaydauky) {
                // Nếu ngày hiện tại < ngày đầu kỳ, lấy tháng trước
                if (month === 0) {
                    // Tháng 1, lùi về tháng 12 năm trước
                    start = new Date(year - 1, 11, ngaydauky);
                } else {
                    start = new Date(year, month - 1, ngaydauky);
                }
            } else {
                // Nếu ngày hiện tại >= ngày đầu kỳ, lấy tháng hiện tại
                start = new Date(year, month, ngaydauky);
            }
        }

        const end = new Date(today);

        // Tính ngày kết thúc kỳ
        let next_month = start.getMonth() + 1;
        let next_year = start.getFullYear();

        if (next_month > 11) {
            next_month = 0;
            next_year += 1;
        }

        let next_start;
        try {
            next_start = new Date(next_year, next_month, ngaydauky);
        } catch (error) {
            // Nếu ngày không hợp lệ (ví dụ: 31/2), lấy ngày cuối tháng
            const lastDayNextMonth = new Date(next_year, next_month + 1, 0).getDate();
            next_start = new Date(next_year, next_month, Math.min(ngaydauky, lastDayNextMonth));
        }

        const end_ky = new Date(next_start.getTime() - 24 * 60 * 60 * 1000); // Trừ 1 ngày
        const prev_end_ky = new Date(start.getTime() - 24 * 60 * 60 * 1000); // Trừ 1 ngày

        return {
            start: start,
            end: end,
            end_ky: end_ky,
            prev_end_ky: prev_end_ky
        };
    }    // Lấy dữ liệu theo chu kỳ thanh toán (từ ngày X tháng này đến ngày X-1 tháng sau)
    getDataByBillingPeriod(monthYear, startDay) {
        const [month, year] = monthYear.split('-').map(Number);

        // FIXED: Tính ngày bắt đầu thực tế của kỳ thanh toán        // monthYear là tháng hiển thị (tháng kết thúc kỳ)        // monthYear là tháng hiển thị (tháng kết thúc kỳ)
        // Cần tìm ngày bắt đầu kỳ để tính đúng
        const endDate = new Date(year, month - 1, startDay - 1); // Ngày kết thúc kỳ (tháng hiện tại)
        const startDate = new Date(year, month - 2, startDay); // Ngày bắt đầu kỳ (tháng trước)

        // Xử lý trường hợp tháng 1 (phải lùi về tháng 12 năm trước)
        if (month === 1) {
            startDate.setFullYear(year - 1);
            startDate.setMonth(11); // Tháng 12 (0-based)
        } const periods = {
            start: startDate,
            end_ky: endDate
        };
        const filteredData = this.dailyData.filter(day => {
            if (!day.Ngày) return false;

            // Chuyển đổi format ngày từ dd-mm-yyyy sang Date object
            const dayDate = new Date(day.Ngày.split('-').reverse().join('-'));

            // Normalize dates to avoid time comparison issues
            const dayDateNormalized = new Date(dayDate.getFullYear(), dayDate.getMonth(), dayDate.getDate());
            const startDateNormalized = new Date(periods.start.getFullYear(), periods.start.getMonth(), periods.start.getDate());
            const endDateNormalized = new Date(periods.end_ky.getFullYear(), periods.end_ky.getMonth(), periods.end_ky.getDate());

            // Kiểm tra xem ngày có nằm trong chu kỳ không
            const isInPeriod = dayDateNormalized >= startDateNormalized && dayDateNormalized <= endDateNormalized;

            return isInPeriod;
        });
        return filteredData;
    }

    // Lấy dữ liệu trong khoảng thời gian
    getDataByDateRange(startDate, endDate) {
        return this.dailyData.filter(day => {
            const dayDate = new Date(day.Ngày.split('-').reverse().join('-'));
            return dayDate >= startDate && dayDate <= endDate && day["Điện tiêu thụ (kWh)"] > 0;
        });
    }

    normalizeYearValue(value) {
        const year = parseInt(value, 10);
        return Number.isNaN(year) ? null : year;
    }

    // Tính tiền điện từ kWh theo công thức bậc thang EVN
    calculateElectricityCost(kwh) {
        if (!kwh || kwh <= 0) return 0;

        const tiers = [
            { limit: 50, price: 1984 },
            { limit: 50, price: 2050 },
            { limit: 100, price: 2380 },
            { limit: 100, price: 2998 },
            { limit: 100, price: 3350 },
            { limit: Infinity, price: 3460 }
        ];

        let totalCost = 0;
        let remainingKwh = kwh;

        for (const tier of tiers) {
            const kwhInTier = Math.min(remainingKwh, tier.limit);
            const cost = kwhInTier * tier.price;
            totalCost += cost;
            remainingKwh -= kwhInTier;
            if (remainingKwh <= 0) break;
        }

        // Thuế 8%
        const tax = totalCost * 0.08;
        const totalWithTax = totalCost + tax;

        return Math.round(totalWithTax);
    }

    buildBillingPeriodRange(month, year, billingCycle) {
        if (billingCycle.type === 'calendar' || (billingCycle.type === 'cycle' && billingCycle.startDay === 1)) {
            const start = new Date(year, month - 1, 1);
            const end = new Date(year, month, 0);
            return { start, end };
        }

        const start = new Date(year, month - 2, billingCycle.startDay);
        const end = new Date(year, month - 1, billingCycle.startDay - 1);

        return { start, end };
    }

    buildPeriodSummaryForMonth(aggregatedMonthlyData, month, year) {
        const billingCycle = this.getBillingCycle();
        const entry = aggregatedMonthlyData.SanLuong.find(item =>
            this.normalizeYearValue(item.Năm) === year && parseInt(item.Tháng, 10) === month
        );
        if (!entry) {
            return null;
        }

        const costEntry = aggregatedMonthlyData.TienDien.find(item =>
            this.normalizeYearValue(item.Năm) === year && parseInt(item.Tháng, 10) === month
        );
        const consumption = typeof entry["Điện tiêu thụ (KWh)"] === 'number'
            ? entry["Điện tiêu thụ (KWh)"]
            : parseFloat(entry["Điện tiêu thụ (KWh)"]) || 0;
        const cost = costEntry
            ? (typeof costEntry["Tiền Điện"] === 'number'
                ? costEntry["Tiền Điện"]
                : parseFloat(costEntry["Tiền Điện"]) || 0)
            : 0;
        const periodRange = this.buildBillingPeriodRange(month, year, billingCycle);

        return {
            month,
            year,
            consumption,
            cost,
            days: null,
            isCurrentPeriod: false,
            period: {
                start: periodRange.start,
                end: periodRange.end
            },
            details: {
                subtotal: null,
                tax: null
            }
        };
    }

    getMonthlyAggregation(filterYear = null) {
        const targetYear = this.normalizeYearValue(filterYear);
        const monthlyData = this.monthlyData || { SanLuong: [], TienDien: [] };
        const billingCycle = this.getBillingCycle();
        const startDay = Math.max(1, Math.min(31, parseInt(billingCycle.startDay, 10) || 1));
        const monthlyMap = new Map();



        const parseDailyDate = (value) => {
            if (!value) return null;
            const parts = String(value).split('-').map(Number);
            if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
            const [day, month, year] = parts;
            const d = new Date(year, month - 1, day);
            return d.getFullYear() === year && d.getMonth() === month - 1 && d.getDate() === day ? d : null;
        };

        const getPeriodKey = (date) => {
            if (startDay === 1) return { year: date.getFullYear(), month: date.getMonth() + 1 };
            let year = date.getFullYear();
            let month = date.getMonth() + 1;
            if (date.getDate() >= startDay) {
                month += 1;
                if (month > 12) { month = 1; year += 1; }
            }
            return { year, month };
        };

        // ƯU TIÊN ĐẦU TIÊN: Dùng monthlyData từ API (chính xác nhất)
        // Chỉ dùng dailyData để bổ sung nếu monthlyData thiếu
        if (Array.isArray(monthlyData.SanLuong) && monthlyData.SanLuong.length > 0) {
            monthlyData.SanLuong.forEach(item => {
                const year = this.normalizeYearValue(item?.Năm);
                const month = parseInt(item?.Tháng, 10);
                if (year === null || !month || month < 1 || month > 12) return;
                // Luôn lọc bỏ dữ liệu trước 2025
                if (year < 2025) return;
                if (targetYear !== null && year !== targetYear) return;
                const key = `${year}-${month}`;

                const raw = item["Điện tiêu thụ (KWh)"];
                const consumption = typeof raw === 'number' ? raw : parseFloat(String(raw ?? '').replace(',', '.')) || 0;
                monthlyMap.set(key, { Tháng: month, Năm: year, consumption });
            });
        }

        // Bổ sung từ dailyData chỉ cho các kỳ không có trong monthlyData
        if (Array.isArray(this.dailyData)) {
            this.dailyData.forEach(day => {
                const date = parseDailyDate(day?.Ngày);
                if (!date || date > new Date()) return;
                const period = getPeriodKey(date);
                if (targetYear !== null && period.year !== targetYear) return;
                const key = `${period.year}-${period.month}`;

                // Chỉ bổ sung nếu monthlyData không có kỳ đó
                if (monthlyMap.has(key)) return;

                const raw = day["Điện tiêu thụ (kWh)"];
                const value = typeof raw === 'number' ? raw : parseFloat(String(raw ?? '').replace(',', '.')) || 0;
                if (!Number.isFinite(value) || value < 0) return;
                const entry = monthlyMap.get(key) || { Tháng: period.month, Năm: period.year, consumption: 0 };
                entry.consumption += value;
                monthlyMap.set(key, entry);
            });
        }

        // TIỀN: ưu tiên hóa đơn thực tế, nếu không có thì tự tính từ sản lượng
        const costMap = new Map();
        if (Array.isArray(monthlyData.TienDien)) {
            monthlyData.TienDien.forEach(item => {
                const year = this.normalizeYearValue(item?.Năm);
                const month = parseInt(item?.Tháng, 10);
                if (year === null || !month || month < 1 || month > 12) return;
                // Luôn lọc bỏ dữ liệu trước 2025
                if (year < 2025) return;
                if (targetYear !== null && year !== targetYear) return;
                const raw = item["Tiền Điện"];
                const cost = typeof raw === 'number' ? raw : parseFloat(String(raw ?? '').replace(',', '.')) || 0;
                // 0/âm không được coi là hóa đơn hợp lệ.
                if (cost > 0) costMap.set(`${year}-${month}`, cost);
            });
        }

        // Tính tiền từ sản lượng cho các kỳ không có tiền hóa đơn
        monthlyMap.forEach((entry, key) => {
            if (!costMap.has(key) && entry.consumption > 0) {
                const calculatedCost = this.calculateElectricityCost(entry.consumption);
                costMap.set(key, calculatedCost);
                console.log(`💰 Calculated cost for ${entry.Tháng}/${entry.Năm}: ${entry.consumption} kWh -> ${calculatedCost} VND`);
            }
        });

        // Chỉ hiển thị các kỳ đã kết thúc. Với chu kỳ 26 -> 25,
        // kỳ 08/2026 là 26/07 -> 25/08 nên ngày 14/08 vẫn chưa hoàn thành;
        // các kỳ 09..12/2026 chắc chắn không được tạo/hiển thị.
        const today = new Date();
        today.setHours(23, 59, 59, 999);
        const isCompletedPeriod = (year, month) => {
            if (startDay === 1) {
                return new Date(year, month, 0, 23, 59, 59, 999) <= today;
            }
            const endMonth = month;
            const endYear = year;
            const endDate = new Date(endYear, endMonth - 1, startDay - 1, 23, 59, 59, 999);
            // Nếu startDay không tồn tại trong tháng (ví dụ ngày 31), JS sẽ tràn tháng;
            // điều chỉnh về ngày cuối tháng trước.
            const lastDay = new Date(endYear, endMonth, 0).getDate();
            const actualEndDay = Math.min(startDay - 1, lastDay);
            const safeEndDate = new Date(endYear, endMonth - 1, actualEndDay, 23, 59, 59, 999);
            return safeEndDate <= today;
        };

        // Tiền hóa đơn phải được giữ độc lập với sản lượng. Nếu API có hóa đơn
        // nhưng không có daily record của kỳ đó thì vẫn phải hiển thị tiền.
        // Đây là điểm quan trọng để các kỳ lịch sử (ví dụ 2025) không mất tiền.
        costMap.forEach((cost, key) => {
            const [yearText, monthText] = key.split('-');
            const year = parseInt(yearText, 10);
            const month = parseInt(monthText, 10);

            // Bỏ qua check isCompletedPeriod cho các kỳ có tiền hóa đơn
            // để đảm bảo các kỳ lịch sử vẫn được hiển thị
            // if (!isCompletedPeriod(year, month)) return;

            if (!monthlyMap.has(key)) {
                monthlyMap.set(key, {
                    Tháng: month,
                    Năm: year,
                    consumption: 0
                });
            }
        });

        // Loại bỏ toàn bộ kỳ tương lai/kỳ hiện tại chưa hoàn tất, kể cả khi
        // monthlyData.SanLuong có sẵn các record 09..12 từ API/cache cũ.
        for (const [key, entry] of monthlyMap.entries()) {
            if (!isCompletedPeriod(entry.Năm, entry.Tháng)) {
                monthlyMap.delete(key);
                costMap.delete(key); // Xóa cả tiền tương ứng
            }
        }

        const sortedEntries = Array.from(monthlyMap.values()).sort((a, b) => a.Năm - b.Năm || a.Tháng - b.Tháng);
        const SanLuong = sortedEntries.map(entry => ({
            Tháng: entry.Tháng,
            Năm: entry.Năm,
            "Điện tiêu thụ (KWh)": entry.consumption
        }));
        const TienDien = sortedEntries.map(entry => ({
            Tháng: entry.Tháng,
            Năm: entry.Năm,
            "Tiền Điện": costMap.get(`${entry.Năm}-${entry.Tháng}`) || 0
        }));

        return { SanLuong, TienDien };
    }

    // Tính toán thống kê tổng quan (bao gồm kỳ hiện tại)
    calculateSummary(filterYear = null) {
        // Đảm bảo monthlyData có structure đúng
        if (!this.monthlyData) {
            this.monthlyData = { SanLuong: [], TienDien: [] };
        }
        if (!this.monthlyData.TienDien) {
            this.monthlyData.TienDien = [];
        }
        if (!this.monthlyData.SanLuong) {
            this.monthlyData.SanLuong = [];
        }

        // Đảm bảo dailyData là array
        if (!this.dailyData || !Array.isArray(this.dailyData)) {
            this.dailyData = [];
        }

        const aggregatedMonthlyData = this.getMonthlyAggregation(filterYear);
        let filteredTienDien = aggregatedMonthlyData.TienDien;
        let filteredSanLuong = aggregatedMonthlyData.SanLuong;
        let filteredDailyData = this.dailyData;

        const targetYear = this.normalizeYearValue(filterYear);

        if (targetYear !== null) {
            filteredDailyData = this.dailyData.filter(day => {
                if (!day.Ngày) return false;
                const year = parseInt(day.Ngày.split('-')[2]);
                return year === targetYear;
            });
        }

        // Tổng tiền điện
        const totalCost = filteredTienDien.reduce((sum, item) => {
            const value = item["Tiền Điện"] || 0;
            return sum + (typeof value === 'number' ? value : parseFloat(value) || 0);
        }, 0);

        // Trung bình hàng tháng
        const monthCount = filteredSanLuong.length;
        const avgMonthlyCost = monthCount > 0
            ? totalCost / monthCount
            : 0;

        // Tổng và trung bình tiêu thụ hàng tháng
        const totalMonthlyConsumption = filteredSanLuong.reduce((sum, item) => {
            const value = item["Điện tiêu thụ (KWh)"] || 0;
            return sum + (typeof value === 'number' ? value : parseFloat(value) || 0);
        }, 0);
        const avgMonthlyConsumption = monthCount > 0
            ? totalMonthlyConsumption / monthCount
            : 0;

        // Trung bình hàng ngày - ƯU TIÊN TÍNH TỪ DỮ LIỆU THÁNG
        // Chỉ dùng dailyData nếu không có dữ liệu tháng
        let avgDailyConsumption = 0;
        
        if (monthCount > 0 && totalMonthlyConsumption > 0) {
            // Tính trung bình hàng ngày từ dữ liệu tháng (chính xác hơn)
            // Giả sử trung bình 30 ngày/tháng
            avgDailyConsumption = totalMonthlyConsumption / (monthCount * 30);
        } else {
            // Fallback: Tính từ dailyData nếu không có dữ liệu tháng
            const validDailyData = filteredDailyData.filter(day => {
                const value = day["Điện tiêu thụ (kWh)"];
                return value && (typeof value === 'number' ? value > 0 : parseFloat(value) > 0);
            });
            const totalDailyConsumption = validDailyData.reduce((sum, day) => {
                const value = day["Điện tiêu thụ (kWh)"];
                return sum + (typeof value === 'number' ? value : parseFloat(value) || 0);
            }, 0);
            avgDailyConsumption = validDailyData.length > 0
                ? totalDailyConsumption / validDailyData.length
                : 0;
        }

        // Tính toán kỳ hiện tại (chỉ khi đang xem năm hiện tại hoặc tất cả)
        const currentYear = new Date().getFullYear();
        const includeCurrentPeriod = targetYear === null || targetYear === currentYear;
        let currentPeriod = null;
        if (includeCurrentPeriod) {
            currentPeriod = this.calculateCurrentPeriod();
        }

        return {
            totalCost,
            avgMonthlyCost,
            avgMonthlyConsumption,
            avgDailyConsumption,
            totalMonthlyConsumption,
            currentPeriod // Thêm dữ liệu kỳ hiện tại
        };
    }    // Thiết lập chu kỳ thanh toán cho tài khoản
    setBillingCycle(account, startDay, type = 'cycle') {
        console.log('🔧 setBillingCycle called:', { account, startDay, type });
        this.billingCycles[account] = { startDay, type };
        console.log('🔧 Billing cycles updated:', this.billingCycles);
    }

    // Lấy thông tin chu kỳ thanh toán hiện tại
    getCurrentBillingInfo() {
        const cycle = this.getBillingCycle();
        if (cycle.type === 'calendar') {
            return {
                type: 'Theo tháng dương lịch',
                description: 'Từ đầu tháng đến cuối tháng'
            };
        } else if (cycle.type === 'cycle' && cycle.startDay === 1) {
            return {
                type: 'Theo chu kỳ thanh toán',
                description: 'Theo chu kỳ thanh toán',
                startDay: cycle.startDay
            };
        } else {
            return {
                type: 'Theo chu kỳ thanh toán',
                description: 'Theo chu kỳ thanh toán',
                startDay: cycle.startDay
            };
        }
    }

    // Lấy base URL cho Ingress hoặc Static Path
    getBaseUrl() {
        const ingressMatch = window.location.pathname.match(/\/api\/hassio_ingress\/[^\/]+/);
        if (ingressMatch) return ingressMatch[0];

        const staticMatch = window.location.pathname.match(/\/npc-monitor/);
        if (staticMatch) return ''; // When served via static path, APIs should be relative to root

        return '';
    }    // Lấy các tháng duy nhất từ dữ liệu (hỗ trợ chu kỳ thanh toán)
    getUniqueMonths(filterYear = null) {
        const billingCycle = this.getBillingCycle();
        console.log('📅 getUniqueMonths - billing cycle:', billingCycle);
        console.log('📅 getUniqueMonths - filter year:', filterYear);

        // Đảm bảo dailyData là array
        if (!this.dailyData || !Array.isArray(this.dailyData) || this.dailyData.length === 0) {
            console.warn('⚠️ getUniqueMonths: No daily data available');
            // Nếu không có daily data, thử lấy từ monthly data
            if (this.monthlyData && this.monthlyData.SanLuong && this.monthlyData.SanLuong.length > 0) {
                let months = this.monthlyData.SanLuong.map(item => {
                    const month = item.Tháng.toString().padStart(2, '0');
                    const year = this.normalizeYearValue(item.Năm) || new Date().getFullYear();
                    return `${month}-${year}`;
                });

                // Lọc theo năm nếu có
                const targetYear = this.normalizeYearValue(filterYear);
                if (targetYear !== null) {
                    months = months.filter(m => m.endsWith(`-${targetYear}`));
                }

                return months.sort((a, b) => {
                    const [m1, y1] = a.split('-');
                    const [m2, y2] = b.split('-');
                    return new Date(y2, m2 - 1) - new Date(y1, m1 - 1);
                });
            }
            return [];
        }

        // Lọc dailyData theo năm nếu có, luôn lọc bỏ dữ liệu trước 2025
        let filteredDailyData = this.dailyData;
        const targetYear = this.normalizeYearValue(filterYear);

        // Luôn lọc bỏ dữ liệu trước 2025
        filteredDailyData = this.dailyData.filter(day => {
            if (!day.Ngày) return false;
            const year = parseInt(day.Ngày.split('-')[2]);
            if (year < 2025) return false;
            if (targetYear !== null && year !== targetYear) return false;
            return true;
        });

        if (billingCycle.type === 'calendar') {
            // Chu kỳ theo tháng dương lịch (cũ)
            const uniqueMonths = [...new Set(filteredDailyData.map(day => day.Ngày?.slice(3, 10)).filter(Boolean))];
            const result = uniqueMonths.sort((a, b) =>
                new Date(b.split('-').reverse().join('-')) -
                new Date(a.split('-').reverse().join('-'))
            );
            return result;
        } else if (billingCycle.type === 'cycle' && billingCycle.startDay === 1) {
            // Chu kỳ được cấu hình thủ công từ ngày 1 - xử lý như tháng dương lịch nhưng với "Kỳ này"
            const uniqueMonths = [...new Set(filteredDailyData.map(day => day.Ngày.slice(3, 10)))];
            const sortedMonths = uniqueMonths.sort((a, b) =>
                new Date(b.split('-').reverse().join('-')) -
                new Date(a.split('-').reverse().join('-'))
            );

            // Thay tháng hiện tại thành "Kỳ này" nếu có và không lọc theo năm
            if (!filterYear) {
                const currentDate = new Date();
                const currentMonthYear = `${(currentDate.getMonth() + 1).toString().padStart(2, '0')}-${currentDate.getFullYear()}`;
                const currentIndex = sortedMonths.indexOf(currentMonthYear);

                console.log('📅 Manual day 1 cycle - current month:', currentMonthYear, 'found at index:', currentIndex);

                if (currentIndex !== -1) {
                    // Thay thế tháng hiện tại bằng "Kỳ này"
                    sortedMonths[currentIndex] = currentMonthYear; // Giữ nguyên format để logic khác hoạt động
                }
            }

                return sortedMonths;
        } else {
            // Chu kỳ thanh toán tùy chỉnh - tạo danh sách kỳ thanh toán
            const result = this.generateBillingPeriods(billingCycle.startDay, filteredDailyData, filterYear);
                return result;
        }
    }// Tạo danh sách các kỳ thanh toán từ dữ liệu có sẵn
    generateBillingPeriods(startDay, filteredDailyData = null, filterYear = null) {
        // Sử dụng filteredDailyData nếu có, nếu không thì dùng this.dailyData
        const dataToUse = filteredDailyData || this.dailyData;
        const targetYear = this.normalizeYearValue(filterYear);

        // Đảm bảo dailyData là array
        if (!dataToUse || !Array.isArray(dataToUse) || dataToUse.length === 0) {
            console.warn('⚠️ generateBillingPeriods: No daily data available');
            return [];
        }

        // Lấy ngày đầu tiên và cuối cùng từ dữ liệu
        const dates = dataToUse
            .map(day => {
                if (!day.Ngày) return null;
                try {
                    return new Date(day.Ngày.split('-').reverse().join('-'));
                } catch (e) {
                    return null;
                }
            })
            .filter(Boolean)
            .sort((a, b) => a - b);

        if (dates.length === 0) return [];

        const firstDate = dates[0];
        const lastDate = dates[dates.length - 1];
        const today = new Date();

        const periods = [];

        // Bắt đầu từ ngày hiện tại và đi ngược về quá khứ
        let currentDate = new Date(today);
        let iterationCount = 0;

        while (currentDate >= firstDate && iterationCount < 24) {
            iterationCount++;

            // Tính chu kỳ thanh toán cho ngày hiện tại
            const periods_info = this.tinhngaydauky(startDay, currentDate);

            // Kiểm tra xem có phải kỳ hiện tại không (kỳ chứa ngày hôm nay)
            const isCurrentPeriod = today >= periods_info.start && today <= periods_info.end_ky;

            // Xử lý kỳ nếu:
            // 1. Có dữ liệu trong kỳ, HOẶC
            // 2. Là kỳ hiện tại (luôn hiển thị kỳ hiện tại dù chưa có đủ dữ liệu)
            const shouldIncludePeriod = periods_info.start <= lastDate || isCurrentPeriod;

            if (shouldIncludePeriod) {
                // Kiểm tra xem chu kỳ này có dữ liệu không
                const hasDataInPeriod = dataToUse.some(day => {
                    const dayDate = new Date(day.Ngày.split('-').reverse().join('-'));
                    return dayDate >= periods_info.start && dayDate <= periods_info.end_ky;
                });

                // Thêm kỳ nếu có dữ liệu HOẶC là kỳ hiện tại
                if (hasDataInPeriod || isCurrentPeriod) {
                    // Logic hiển thị tháng theo chuẩn EVN:
                    // Kỳ thanh toán được đặt tên theo tháng kết thúc (tháng hóa đơn)
                    // VD: Kỳ 10/6 → 9/7 = "Kỳ tháng 7" vì hóa đơn phát hành tháng 7
                    let displayMonth, displayYear;

                    if (isCurrentPeriod && startDay === 1) {
                        // Kỳ hiện tại và bắt đầu từ ngày 1: luôn dùng tháng hiện tại
                        displayMonth = today.getMonth() + 1;
                        displayYear = today.getFullYear();
                    } else if (startDay === 1) {
                        // Chu kỳ theo tháng dương lịch (không phải kỳ hiện tại): dùng tháng bắt đầu
                        displayMonth = periods_info.start.getMonth() + 1;
                        displayYear = periods_info.start.getFullYear();
                    } else {
                        // Chu kỳ tùy chỉnh: dùng tháng kết thúc (tháng hóa đơn)
                        displayMonth = periods_info.end_ky.getMonth() + 1;
                        displayYear = periods_info.end_ky.getFullYear();
                    }

                    // Filter theo năm nếu có
                    if (targetYear !== null && displayYear !== targetYear) {
                        currentDate.setMonth(currentDate.getMonth() - 1);
                        continue;
                    }

                    const periodLabel = `${displayMonth.toString().padStart(2, '0')}-${displayYear}`;

                    if (!periods.includes(periodLabel)) {
                        periods.push(periodLabel);
                    }
                }
            }

            // Lùi về tháng trước
            currentDate.setMonth(currentDate.getMonth() - 1);
        }

        // Đã sắp xếp từ mới nhất đến cũ nhất rồi
        return periods;
    }

    // Tính trend cho summary cards theo chu kỳ thanh toán
    calculateTrendData(recentMonths) {
        const billingCycle = this.getBillingCycle();
        const today = new Date();

        // Ưu tiên dữ liệu từ sensor, nếu không có thì tính toán
        const sensorData = this.currentPeriodFromSensor;

        return recentMonths.map((monthYear, index) => {
            const monthNum = monthYear.split('-')[0];
            const isCurrentPeriod = index === 0; // Kỳ đầu tiên là kỳ hiện tại

            // Nếu là kỳ hiện tại, sử dụng dữ liệu từ sensor
            if (isCurrentPeriod) {
                // Lấy dữ liệu chi tiết cho min/max/avg từ dailyData
                const periodInfo = this.tinhngaydauky(billingCycle.startDay, today);
                const detailData = this.dailyData.filter(d => {
                    if (!d.Ngày || d["Điện tiêu thụ (kWh)"] <= 0) return false;
                    const dayDate = new Date(d.Ngày.split('-').reverse().join('-'));
                    return dayDate >= periodInfo.start && dayDate <= today;
                });

                let min = 0, max = 0, avg = 0, minDay = '', maxDay = '';
                let trend = 'flat', trendValue = 0, trendPercent = 0, badge = '';
                let sparkline = '';

                // Sử dụng dữ liệu từ sensor nếu có
                let totalConsumption = 0;
                let monthlyCost = 0;

                // BẮT BUỘC lấy từ sensor
                if (sensorData) {
                    totalConsumption = sensorData.tieu_thu_ky_nay || 0;
                    monthlyCost = sensorData.tien_dien_ky_nay || 0;
                    console.log('⚡ Using SENSOR data for current period:', totalConsumption, 'kWh,', monthlyCost, 'VND');
                } else {
                    console.warn('⚠️ No sensor data available for current period!');
                }

                if (detailData.length > 0) {
                    const values = detailData.map(d => d["Điện tiêu thụ (kWh)"]);
                    min = Math.min(...values);
                    max = Math.max(...values);
                    avg = values.reduce((a, b) => a + b, 0) / values.length;
                    minDay = detailData.find(d => d["Điện tiêu thụ (kWh)"] === min)?.Ngày || '';
                    maxDay = detailData.find(d => d["Điện tiêu thụ (kWh)"] === max)?.Ngày || '';

                    // Tính trend cho kỳ hiện tại so với kỳ trước đó
                    if (recentMonths.length > 1) {
                        const prevMonthYear = recentMonths[1];
                        let prevArr;

                        if (billingCycle.type === 'calendar' || (billingCycle.type === 'cycle' && billingCycle.startDay === 1)) {
                            prevArr = this.dailyData.filter(d =>
                                d.Ngày && d.Ngày.slice(3, 10) === prevMonthYear && d["Điện tiêu thụ (kWh)"] > 0
                            );
                        } else {
                            prevArr = this.getDataByBillingPeriod(prevMonthYear, billingCycle.startDay)
                                .filter(d => d["Điện tiêu thụ (kWh)"] > 0);
                        }

                        const prevAvg = prevArr.length > 0 ?
                            prevArr.map(d => d["Điện tiêu thụ (kWh)"]).reduce((a, b) => a + b, 0) / prevArr.length : 0;

                        if (prevAvg > 0 && avg > 0) {
                            trendValue = avg - prevAvg;
                            trendPercent = (trendValue / prevAvg) * 100;

                            if (trendValue > 0.01) trend = 'up';
                            else if (trendValue < -0.01) trend = 'down';

                            if (trendPercent > 20) badge = '<span class="trend-badge">Tăng mạnh</span>';
                            else if (trendPercent < -20) badge = '<span class="trend-badge">Giảm mạnh</span>';
                        }
                    }

                    // Tạo sparkline SVG
                    const points = values.map((v, i) =>
                        `${i * (60 / (values.length - 1))},${18 - (v - min) / (max - min + 0.01) * 16}`
                    ).join(' ');
                    sparkline = `<svg class='sparkline'><polyline fill='none' stroke='#e961ab' stroke-width='2' points='${points}'/></svg>`;
                }

                return {
                    monthNum,
                    monthYear,
                    min,
                    max,
                    avg,
                    minDay,
                    maxDay,
                    trend,
                    trendValue,
                    trendPercent,
                    badge,
                    sparkline,
                    dataCount: detailData.length,
                    isCurrentPeriod: true,
                    totalConsumption,
                    monthlyCost
                };
            }

            // Kỳ đã qua: lấy dữ liệu theo chu kỳ thanh toán
            let monthDataArr;
            if (billingCycle.type === 'calendar' || (billingCycle.type === 'cycle' && billingCycle.startDay === 1)) {
                monthDataArr = this.dailyData.filter(d =>
                    d.Ngày && d.Ngày.slice(3, 10) === monthYear && d["Điện tiêu thụ (kWh)"] > 0
                );
            } else {
                monthDataArr = this.getDataByBillingPeriod(monthYear, billingCycle.startDay)
                    .filter(d => d["Điện tiêu thụ (kWh)"] > 0);
            }

            let min = 0, max = 0, avg = 0, minDay = '', maxDay = '';
            let trend = 'flat', trendValue = 0, trendPercent = 0, badge = '';
            let sparkline = '';
            let totalConsumption = 0, monthlyCost = 0;

            if (monthDataArr.length > 0) {
                const values = monthDataArr.map(d => d["Điện tiêu thụ (kWh)"]);
                min = Math.min(...values);
                max = Math.max(...values);
                avg = values.reduce((a, b) => a + b, 0) / values.length;
                totalConsumption = values.reduce((a, b) => a + b, 0);
                minDay = monthDataArr.find(d => d["Điện tiêu thụ (kWh)"] === min)?.Ngày || '';
                maxDay = monthDataArr.find(d => d["Điện tiêu thụ (kWh)"] === max)?.Ngày || '';

                // Tìm dữ liệu tiền điện từ monthlyData (theo cả Tháng và Năm)
                const [monthStr, yearStr] = monthYear.split('-');
                const targetYear = this.normalizeYearValue(yearStr);
                const monthlyDataItem = this.monthlyData?.TienDien?.find(item => {
                    const itemMonth = item.Tháng.toString().padStart(2, '0');
                    const itemYear = this.normalizeYearValue(item.Năm) || new Date().getFullYear();
                    const targetMonth = monthNum.toString().padStart(2, '0');
                    return itemMonth === targetMonth && itemYear === targetYear;
                });

                if (monthlyDataItem && monthlyDataItem["Tiền Điện"]) {
                    monthlyCost = parseInt(monthlyDataItem["Tiền Điện"] || 0);
                } else {
                    if (totalConsumption > 0) {
                        const costCalculation = this.tinhTienDien(totalConsumption);
                        monthlyCost = costCalculation.total;
                    } else {
                        monthlyCost = 0;
                    }
                }

                // Tính trend so với chu kỳ trước
                if (index < recentMonths.length - 1) {
                    const nextMonthYear = recentMonths[index + 1];
                    let prevArr;

                    if (billingCycle.type === 'calendar' || (billingCycle.type === 'cycle' && billingCycle.startDay === 1)) {
                        prevArr = this.dailyData.filter(d =>
                            d.Ngày && d.Ngày.slice(3, 10) === nextMonthYear && d["Điện tiêu thụ (kWh)"] > 0
                        );
                    } else {
                        prevArr = this.getDataByBillingPeriod(nextMonthYear, billingCycle.startDay)
                            .filter(d => d["Điện tiêu thụ (kWh)"] > 0);
                    }

                    const prevAvg = prevArr.length > 0 ?
                        prevArr.map(d => d["Điện tiêu thụ (kWh)"]).reduce((a, b) => a + b, 0) / prevArr.length : 0;

                    if (prevAvg > 0 && avg > 0) {
                        trendValue = avg - prevAvg;
                        trendPercent = (trendValue / prevAvg) * 100;

                        if (trendValue > 0.01) trend = 'up';
                        else if (trendValue < -0.01) trend = 'down';

                        // Badge nếu tăng/giảm mạnh
                        if (trendPercent > 20) badge = '<span class="trend-badge">Tăng mạnh</span>';
                        else if (trendPercent < -20) badge = '<span class="trend-badge">Giảm mạnh</span>';
                    }
                }

                // Tạo sparkline SVG
                const points = values.map((v, i) =>
                    `${i * (60 / (values.length - 1))},${18 - (v - min) / (max - min + 0.01) * 16}`
                ).join(' ');
                sparkline = `<svg class='sparkline'><polyline fill='none' stroke='#e961ab' stroke-width='2' points='${points}'/></svg>`;
            }

            return {
                monthNum,
                monthYear,
                min,
                max,
                avg,
                minDay,
                maxDay,
                trend,
                trendValue,
                trendPercent,
                badge,
                sparkline,
                dataCount: monthDataArr.length,
                isCurrentPeriod: false,
                totalConsumption,
                monthlyCost
            };
        });
    }

    // Tính tiền điện theo bậc thang (từ NPC utils.py)
    tinhTienDien(kwh) {
        if (!kwh || kwh <= 0) {
            return { total: 0, details: {} };
        }

        const tiers = [
            { limit: 50, price: 1984 },
            { limit: 50, price: 2050 },
            { limit: 100, price: 2380 },
            { limit: 100, price: 2998 },
            { limit: 100, price: 3350 },
            { limit: Infinity, price: 3460 }
        ];

        let totalCost = 0;
        let remainingKwh = kwh;
        let tierDetails = [];

        for (let i = 0; i < tiers.length; i++) {
            const tier = tiers[i];
            const kwhInTier = Math.min(remainingKwh, tier.limit);
            const cost = kwhInTier * tier.price;

            totalCost += cost;
            tierDetails.push({
                tier: i + 1,
                price: tier.price,
                kwh: kwhInTier,
                cost: cost
            });

            remainingKwh -= kwhInTier;
            if (remainingKwh <= 0) break;
        }

        const tax = totalCost * 0.08;
        const totalWithTax = totalCost + tax;

        return {
            total: Math.round(totalWithTax),
            details: {
                subtotal: Math.round(totalCost),
                tax: Math.round(tax),
                tiers: tierDetails
            }
        };
    }    // Tính toán dữ liệu kỳ hiện tại
    calculateCurrentPeriod() {
        const billingCycle = this.getBillingCycle();
        const today = new Date();

        // Tính chu kỳ hiện tại
        const currentPeriod = this.tinhngaydauky(billingCycle.startDay, today);

        // Lấy dữ liệu trong kỳ hiện tại (chỉ từ ngày đầu kỳ đến hôm nay) để đếm số ngày
        const currentPeriodData = this.dailyData.filter(day => {
            if (!day.Ngày) return false;
            const dayDate = new Date(day.Ngày.split('-').reverse().join('-'));
            return dayDate >= currentPeriod.start && dayDate <= today &&
                day["Điện tiêu thụ (kWh)"] > 0;
        });

        // Xác định tháng hiển thị
        let displayMonth, displayYear;
        if (billingCycle.type === 'calendar') {
            displayMonth = today.getMonth() + 1;
            displayYear = today.getFullYear();
        } else if (billingCycle.startDay === 1 && billingCycle.type === 'cycle') {
            displayMonth = today.getMonth() + 1;
            displayYear = today.getFullYear();
        } else {
            displayMonth = currentPeriod.end_ky.getMonth() + 1;
            displayYear = currentPeriod.end_ky.getFullYear();
        }

        // ƯU TIÊN: Lấy dữ liệu từ sensor API nếu có
        if (this.currentPeriodFromSensor && this.currentPeriodFromSensor.tieu_thu_ky_nay > 0) {
            const consumption = this.currentPeriodFromSensor.tieu_thu_ky_nay;
            const cost = this.currentPeriodFromSensor.tien_dien_ky_nay;
            const billCalculation = this.tinhTienDien(consumption);

            console.log('⚡ calculateCurrentPeriod: Using SENSOR data:', consumption, 'kWh,', cost, 'VND');

            return {
                month: displayMonth,
                year: displayYear,
                consumption: Math.round(consumption * 100) / 100,
                cost: cost,
                days: currentPeriodData.length,
                isCurrentPeriod: true,
                period: {
                    start: currentPeriod.start,
                    end: currentPeriod.end_ky
                },
                details: billCalculation.details
            };
        }

        // Không có sensor data
        console.warn('⚠️ calculateCurrentPeriod: No sensor data available!');
        return null;
    }

    // Kiểm tra xem tháng có phải là kỳ hiện tại không
    isCurrentPeriodMonth(monthYear, index) {
        const billingCycle = this.getBillingCycle();
        const today = new Date();

        if (billingCycle.type === 'calendar') {
            // Tháng dương lịch: kiểm tra có phải tháng hiện tại không
            const currentMonthYear = `${(today.getMonth() + 1).toString().padStart(2, '0')}-${today.getFullYear()}`;
            return monthYear === currentMonthYear;
        } else if (billingCycle.type === 'cycle' && billingCycle.startDay === 1) {
            // Chu kỳ được cấu hình thủ công từ ngày 1: kiểm tra có phải tháng hiện tại không
            const currentMonthYear = `${(today.getMonth() + 1).toString().padStart(2, '0')}-${today.getFullYear()}`;
            return monthYear === currentMonthYear;
        } else {
            // Chu kỳ thanh toán tùy chỉnh: chỉ tháng đầu tiên là kỳ hiện tại
            return index === 0;
        }
    }

    // Lấy danh sách các năm có trong dữ liệu
    getAvailableYears() {
        const years = new Set();

        // Lấy từ monthly data
        if (this.monthlyData && this.monthlyData.SanLuong) {
            this.monthlyData.SanLuong.forEach(item => {
                if (item.Năm) {
                    const year = this.normalizeYearValue(item.Năm);
                    if (year !== null) {
                        years.add(year);
                    }
                }
            });
        }

        // Lấy từ daily data
        if (this.dailyData && Array.isArray(this.dailyData)) {
            this.dailyData.forEach(day => {
                if (day.Ngày) {
                    const year = parseInt(day.Ngày.split('-')[2]);
                    if (!isNaN(year)) {
                        years.add(year);
                    }
                }
            });
        }

        return Array.from(years).sort((a, b) => b - a);
    }

    // Lọc monthly data theo năm. Không tự tạo 12 tháng rỗng/tương lai.
    getFilteredMonthlyData(year) {
        const targetYear = this.normalizeYearValue(year);
        const aggregated = this.getMonthlyAggregation(targetYear);

        // Khi chọn "Tất cả năm": hiển thị toàn bộ các kỳ thực sự có dữ liệu,
        // không cắt thành 12 tháng gần nhất (ví dụ 09/2025 -> 08/2026).
        // Khi chọn một năm: chỉ hiển thị các kỳ của năm đó có dữ liệu.
        return {
            SanLuong: aggregated.SanLuong.filter(item => {
                if (targetYear === null) return true;
                return this.normalizeYearValue(item.Năm) === targetYear;
            }),
            TienDien: aggregated.TienDien.filter(item => {
                if (targetYear === null) return true;
                return this.normalizeYearValue(item.Năm) === targetYear;
            })
        };
    }

}

// Export cho sử dụng global
window.DataManager = DataManager;
