package paypal

import (
	"fmt"
	"math/rand"
	"strings"
)

var firstNames = []string{"James", "William", "John", "Michael", "David", "Sarah", "Emily", "Ashley"}
var lastNames = []string{"Smith", "Brown", "Davis", "Wilson", "Taylor", "Lewis", "Moore", "Johnson"}
var streets = []string{"Maple Dr", "Cedar Ln", "Park Ave"}

type identity struct {
	Name       string
	Email      string
	Phone      string
	Country    string
	State      string
	City       string
	PostalCode string
	Line1      string
}

func randomIdentity(country, geoCountry, region, city, postal, email string) identity {
	first := firstNames[rand.Intn(len(firstNames))]
	last := lastNames[rand.Intn(len(lastNames))]
	if email == "" {
		email = fmt.Sprintf("%s%s%d@gmail.com", strings.ToLower(first), strings.ToLower(last), rand.Intn(9000)+1000)
	}

	defaults := identity{
		Country:    "JP",
		State:      "Tokyo",
		City:       "Tokyo",
		PostalCode: "150-0001",
	}
	billingCountry := strings.ToUpper(strings.TrimSpace(country))
	switch billingCountry {
	case "US":
		defaults.Country = "US"
		defaults.State = "CA"
		defaults.City = "San Francisco"
		defaults.PostalCode = "94105"
	case "FR":
		defaults.Country = "FR"
		defaults.State = "Ile-de-France"
		defaults.City = "Paris"
		defaults.PostalCode = "75001"
	case "BR":
		defaults.Country = "BR"
		defaults.State = "SP"
		defaults.City = "Sao Paulo"
		defaults.PostalCode = "01001-000"
		defaults.Phone = fmt.Sprintf("+55119%08d", rand.Intn(100000000))
	}
	if strings.EqualFold(strings.TrimSpace(geoCountry), defaults.Country) {
		if region != "" {
			defaults.State = region
		}
		if city != "" {
			defaults.City = city
		}
		if postal != "" {
			defaults.PostalCode = postal
		}
	}
	defaults.Name = first + " " + last
	defaults.Email = email
	defaults.Line1 = fmt.Sprintf("%d %s", rand.Intn(900)+100, streets[rand.Intn(len(streets))])
	return defaults
}
