package register

import (
	"fmt"
	"math/rand"
	"strings"
	"time"

	"autoteam-f/protocol-register/internal/model"
)

// Human-like password words (mirrors core/identity.py) used only when the
// caller does not supply a password.
var identityPasswordWords = []string{
	"Apple", "Beach", "Coffee", "Dragon", "Eagle", "Forest", "Galaxy", "Harbor",
	"Island", "Jasper", "Kitten", "Lotus", "Maple", "Nebula", "Orange", "Pepper",
	"Quartz", "River", "Sunset", "Tiger", "Velvet", "Willow", "Yellow", "Zephyr",
	"Autumn", "Breeze", "Castle", "Diamond", "Ember", "Falcon", "Ginger", "Hazel",
	"Indigo", "Jungle", "Lemon", "Mango", "Ocean", "Panda", "Raven", "Silver",
	"Thunder",
}

// Fallback identity pool used when the caller does not supply one. The Python
// bridge normally generates the identity from core/identity.py; this keeps the
// Go service self-sufficient (and avoids shipping the hardcoded "Alex Chen").
var identityFirstNames = []string{
	"Aaron", "Abigail", "Adam", "Alice", "Amelia", "Andrew", "Anna", "Anthony",
	"Austin", "Ava", "Benjamin", "Brandon", "Brian", "Caleb", "Carter", "Charles",
	"Charlotte", "Chloe", "Christopher", "Claire", "Connor", "Daniel", "David",
	"Dylan", "Edward", "Elena", "Elizabeth", "Ella", "Emily", "Emma", "Ethan",
	"Evan", "Evelyn", "Gabriel", "Grace", "Hannah", "Harper", "Henry", "Isaac",
	"Isabella", "Jack", "Jacob", "James", "Jason", "Jennifer", "Jessica", "John",
	"Jonathan", "Jordan", "Joseph", "Joshua", "Julia", "Justin", "Katherine",
	"Kevin", "Kyle", "Laura", "Leah", "Liam", "Lily", "Logan", "Lucas", "Madison",
	"Mark", "Mary", "Mason", "Matthew", "Megan", "Mia", "Michael", "Michelle",
	"Natalie", "Nathan", "Nicholas", "Noah", "Olivia", "Owen", "Patrick", "Paul",
	"Peter", "Rachel", "Rebecca", "Robert", "Ryan", "Sarah", "Savannah", "Scott",
	"Sean", "Sophia", "Stephen", "Thomas", "Tyler", "Victoria", "William", "Zoe",
}

var identityLastNames = []string{
	"Adams", "Allen", "Anderson", "Bailey", "Baker", "Bell", "Bennett", "Brooks",
	"Brown", "Campbell", "Carter", "Clark", "Collins", "Cook", "Cooper", "Cox",
	"Davis", "Diaz", "Edwards", "Evans", "Fisher", "Ford", "Foster", "Garcia",
	"Gonzalez", "Gray", "Green", "Hall", "Harris", "Henderson", "Hernandez",
	"Hill", "Howard", "Hughes", "Jackson", "James", "Jenkins", "Johnson", "Jones",
	"Kelly", "King", "Lee", "Lewis", "Long", "Lopez", "Martin", "Martinez",
	"Mitchell", "Moore", "Morgan", "Morris", "Murphy", "Myers", "Nelson", "Nguyen",
	"Parker", "Patel", "Perez", "Peterson", "Phillips", "Powell", "Price",
	"Ramirez", "Reed", "Reyes", "Richardson", "Rivera", "Roberts", "Robinson",
	"Rodriguez", "Rogers", "Ross", "Russell", "Sanchez", "Sanders", "Scott",
	"Simmons", "Smith", "Stewart", "Sullivan", "Taylor", "Thomas", "Thompson",
	"Torres", "Turner", "Walker", "Ward", "Washington", "Watson", "White",
	"Williams", "Wilson", "Wood", "Wright", "Young",
}

func randomIdentity() (string, string) {
	first := identityFirstNames[rand.Intn(len(identityFirstNames))]
	last := identityLastNames[rand.Intn(len(identityLastNames))]
	name := first + " " + last

	today := time.Now()
	latestYear := today.Year() - 27
	if latestYear > 1999 {
		latestYear = 1999
	}
	earliestYear := today.Year() - 46
	if earliestYear > latestYear {
		earliestYear = latestYear
	}
	year := earliestYear + rand.Intn(latestYear-earliestYear+1)
	month := 1 + rand.Intn(12)
	day := 1 + rand.Intn(28)
	birthdate := fmt.Sprintf("%04d-%02d-%02d", year, month, day)
	return name, birthdate
}

func randomPassword() string {
	word1 := identityPasswordWords[rand.Intn(len(identityPasswordWords))]
	word2 := strings.ToLower(identityPasswordWords[rand.Intn(len(identityPasswordWords))])
	digitCount := 3
	if rand.Intn(2) == 0 {
		digitCount = 4
	}
	digits := make([]byte, digitCount)
	for i := range digits {
		digits[i] = byte('0' + rand.Intn(10))
	}
	symbols := []byte{'!', '@', '#', '$'}
	return fmt.Sprintf("%s%s%s%c", word1, word2, digits, symbols[rand.Intn(len(symbols))])
}

// resolveIdentity returns the caller-supplied name/birthdate, filling any blank
// field with a random value so every registration gets a distinct identity.
func resolveIdentity(identity model.Identity) (string, string) {
	name := strings.TrimSpace(identity.Name)
	birthdate := strings.TrimSpace(identity.Birthdate)
	if name != "" && birthdate != "" {
		return name, birthdate
	}
	randomName, randomBirthdate := randomIdentity()
	if name == "" {
		name = randomName
	}
	if birthdate == "" {
		birthdate = randomBirthdate
	}
	return name, birthdate
}
