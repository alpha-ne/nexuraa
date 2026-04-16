from django.conf import settings
from django.db import models
from django.utils import timezone


class PlanTier(models.Model):
	name = models.CharField(max_length=80)
	slug = models.SlugField(unique=True)
	description = models.TextField(blank=True)
	base_premium = models.DecimalField(max_digits=10, decimal_places=2)
	weekly_coverage = models.DecimalField(max_digits=10, decimal_places=2)
	features = models.JSONField(default=list, blank=True)
	is_recommended = models.BooleanField(default=False)
	is_active = models.BooleanField(default=True)
	sort_order = models.PositiveIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["sort_order", "name"]

	def __str__(self):
		return self.name


class Policy(models.Model):
	STATUS_CHOICES = [
		("pending", "Pending"),
		("active", "Active"),
		("cancelled", "Cancelled"),
		("lapsed", "Lapsed"),
	]

	worker = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="policies",
	)
	plan_tier = models.ForeignKey(PlanTier, on_delete=models.PROTECT, related_name="policies")
	weekly_premium = models.DecimalField(max_digits=10, decimal_places=2)
	weekly_coverage = models.DecimalField(max_digits=10, decimal_places=2)
	start_date = models.DateField()
	end_date = models.DateField()
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
	mandate_confirmed = models.BooleanField(default=False)
	razorpay_subscription_id = models.CharField(max_length=120, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-start_date"]

	def __str__(self):
		return f"{self.worker} - {self.plan_tier} ({self.status})"

	@property
	def coverage_display(self):
		try:
			return f"₹{int(self.weekly_coverage):,}"
		except Exception:
			return f"₹{self.weekly_coverage}"

	@property
	def premium_display(self):
		try:
			return f"₹{int(self.weekly_premium):,}/week"
		except Exception:
			return f"₹{self.weekly_premium}/week"

	@property
	def days_remaining(self):
		return max((self.end_date - timezone.now().date()).days, 0)
